"""Inbound leads from outside the Google Sheets (website first; WhatsApp and
Facebook later use the same path).

Website rule (from the business): only bookings that paid the ₹99
reservation become leads — they are PREMIUM leads. Every webhook call is
logged in lead_submissions whether or not a lead is created, and each paid
entry is a new lead (a repeat call with the same entry/payment id is a
retry, not a new lead). Bookings whose payment failed, was cancelled, timed
out or was abandoned are kept there as "payment_failed" — listed under Leads
→ Failed payments, never a lead; when the same entry is later sent as paid
it becomes the lead as usual.

Routing: preferred store → that store's team leader → one of that team
leader's telecallers (fewest leads assigned today first). No store match or
no team leader → the team leader of the customer's area / country gets it
to assign by hand (fallback_team_leader); failing that it stays unassigned
and admins are alerted.
"""
from __future__ import annotations

import re
from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import (
    LeadSubmission, Role, Store, StoreMcpAlias, TeleAppointment, TeleCallLead, TeleSheetAssignment, User,
)
from .config import ensure_go_live, get_automation
from .night_queue import queue_lead, should_queue
from .engine import (
    add_activity, admin_ids, create_alert, create_followup, norm_phone, refresh_derived,
    team_leader_ids, transfer_ownership,
)
from .timeutil import add_working_minutes, from_ist, ist_day_bounds_utc, ist_today, parse_sheet_datetime, to_ist, utcnow

FAILED_STATUS = "payment_failed"  # lead_submissions.status of a booking that didn't pay
PAID_STATES = {"paid", "success", "successful", "captured", "completed", "complete", "true", "1", "yes"}

# Accepted field names for each value (third-party forms name things freely).
FIELDS = {
    "full_name": ["full_name", "fullname", "name", "your_name", "customer_name"],
    "phone": ["phone", "mobile", "mobile_number", "phone_number", "whatsapp", "mobile_whatsapp", "contact"],
    "email": ["email", "email_address", "mail"],
    "country": ["country"],
    "state": ["state", "region", "province"],
    "place": ["place", "city", "location", "area"],
    "store": ["preferred_store", "store", "store_name", "branch", "shop"],
    "store_id": ["store_id", "branch_id", "shop_id"],
    "brand": ["phone_brand", "brand", "device_brand"],
    "model": ["phone_model", "model", "device_model", "device"],
    "preferred_date": ["preferred_date", "date", "appointment_date", "booking_date"],
    "payment_ref": ["payment_id", "payment_ref", "transaction_id", "txn_id", "razorpay_payment_id", "order_id"],
    "payment_status": ["payment_status", "status", "paid"],
    "amount": ["amount", "payment_amount", "paid_amount"],
    "entry_id": ["entry_id", "submission_id", "booking_id", "lead_id", "id"],
    "paid_at": ["paid_at", "payment_time", "created_at", "submitted_at"],
    "payment_error": ["payment_error", "error", "error_description", "failure_reason", "reason"],
}


def _key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", str(k).strip().lower()).strip("_")


def pick(payload: dict, field: str) -> str:
    flat = {_key(k): v for k, v in payload.items()}
    for name in FIELDS[field]:
        v = flat.get(name)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def is_paid(payload: dict) -> bool:
    status = pick(payload, "payment_status").lower()
    if status:
        return status in PAID_STATES
    return bool(pick(payload, "payment_ref"))  # no status field → a payment id means paid


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


async def match_store(db: AsyncSession, store_text: str, store_id: str) -> Store | None:
    """The store for a preferred-store text / id, swapped for the record of
    the same shop that has a team leader when needed."""
    return await canonical_store(db, await _match_store(db, store_text, store_id))


async def _match_store(db: AsyncSession, store_text: str, store_id: str) -> Store | None:
    """Our store for the form's preferred store: by id, exact name, MCP
    alias, then a unique partial name match."""
    if store_id.isdigit():
        st = (await db.execute(select(Store).where(Store.id == int(store_id), Store.is_active == True))).scalar_one_or_none()  # noqa: E712
        if st:
            return st
    key = _norm(store_text)
    if not key:
        return None
    stores = (await db.execute(select(Store).where(Store.is_active == True))).scalars().all()  # noqa: E712
    for st in stores:
        if _norm(st.name) == key or _norm(st.mcp_shop_name) == key:
            return st
    alias = (await db.execute(select(StoreMcpAlias.store_id).where(
        func.lower(StoreMcpAlias.mcp_shop_name) == store_text.strip().lower()))).scalar()
    if alias:
        return next((st for st in stores if st.id == alias), None)
    partial = [st for st in stores if len(key) >= 4 and (key in _norm(st.name) or (_norm(st.name) and _norm(st.name) in key))]
    if len(partial) == 1:
        return partial[0]
    # Place names the forms and website use ("Hitech City North",
    # "Kodambakkam, Chennai", "Kanhagad"): the one shop they name, if any.
    from ..store_portfolio import shop_of, shops_mentioned
    shops = shops_mentioned(store_text, None) | ({shop_of(store_text)} - {None})
    return await store_for_shop(db, shops.pop()) if len(shops) == 1 else None


async def store_for_shop(db: AsyncSession, shop: str) -> Store | None:
    """The store record a shop's leads should go to. A shop can have several
    records (e.g. "TVM" and "Kerala Trivandrum"); prefer the one with a real
    team leader, then the one MCP reports sales for."""
    from ..store_portfolio import shop_of
    stores = [st for st in (await db.execute(select(Store).where(Store.is_active == True))).scalars().all()  # noqa: E712
              if shop_of(st.name) == shop]
    if not stores:
        return None
    aliased = set((await db.execute(select(StoreMcpAlias.store_id).where(
        StoreMcpAlias.store_id.in_([st.id for st in stores])))).scalars().all())
    ranked = []
    for st in stores:
        ranked.append((await _real_team_leader(db, st) is None, st.id not in aliased, st.id, st))
    return min(ranked)[-1]


async def canonical_store(db: AsyncSession, store: Store | None) -> Store | None:
    """Same shop, but the record that can actually take leads: a matched
    duplicate without a team leader is swapped for the one with one."""
    if store is None or await _real_team_leader(db, store):
        return store
    from ..store_portfolio import shop_of
    shop = shop_of(store.name)
    better = await store_for_shop(db, shop) if shop else None
    return better if better and await _real_team_leader(db, better) else store


async def _real_team_leader(db: AsyncSession, store: Store | None) -> User | None:
    if not store or not store.team_leader_id:
        return None
    tl = (await db.execute(select(User).where(User.id == store.team_leader_id))).scalar_one_or_none()
    if not tl or not tl.is_active or tl.name.strip().lower() == "unassigned":
        return None  # placeholder "Unassigned" TL from common.get_or_create_unassigned_store
    return tl


async def fallback_team_leader(db: AsyncSession, texts: list[str | None], country: str | None = None) -> User | None:
    """Team leader for a lead no store could be found for, who then assigns
    it by hand: the TL with the most shops in the area the texts name
    ("Nearest store (Tamil Nadu)", a state or city), else the one TL of the
    customer's country if a single TL covers it (UAE). None when unclear."""
    from ..store_portfolio import area_of_store
    stores = (await db.execute(select(Store).where(Store.is_active == True))).scalars().all()  # noqa: E712
    area = next((a for a in (area_of_store(t) for t in texts if t) if a), None)
    if area:
        counts: dict[int, int] = {}
        for st in stores:
            if area_of_store(st.name, st.region or "") == area and await _real_team_leader(db, st):
                counts[st.team_leader_id] = counts.get(st.team_leader_id, 0) + 1
        if counts:
            tl_id = sorted(counts, key=lambda i: (-counts[i], i))[0]
            return (await db.execute(select(User).where(User.id == tl_id))).scalar_one()
    if country:
        tls = {st.team_leader_id for st in stores
               if _norm(st.country) == _norm(country) and await _real_team_leader(db, st)}
        if len(tls) == 1:
            return (await db.execute(select(User).where(User.id == tls.pop()))).scalar_one()
    return None


async def store_telecallers(db: AsyncSession, store: Store, *, available_only: bool = True) -> list[User]:
    """Active telecallers assigned to this store (Settings → Users): as their
    own store or as one of their further stores."""
    from ...models.models import UserStoreAccess
    extra = select(UserStoreAccess.user_id).where(UserStoreAccess.store_id == store.id)
    q = (select(User).join(Role, Role.id == User.role_id)
         .where(Role.name == "Telecaller", User.is_active == True,  # noqa: E712
                or_(User.store_id == store.id, User.id.in_(extra))))
    users = list((await db.execute(q)).scalars().all())
    return [u for u in users if u.available_for_leads is not False] if available_only else users


async def lead_store(db: AsyncSession, lead: TeleCallLead) -> Store | None:
    """The store a lead belongs to: its own, else the shop whose own city
    sheet it came from (a sheet covering several shops gives none)."""
    if lead.store_id:
        return await db.get(Store, lead.store_id)
    from ..store_portfolio import shop_of_sheet
    shop = shop_of_sheet(lead.sheet_tl_name or "")
    return await store_for_shop(db, shop) if shop else None


async def pick_telecaller(db: AsyncSession, tl: User, store: Store | None = None) -> User | None:
    """Available telecaller with the fewest leads assigned today (leads
    waiting for them in the night queue count too): one of the store's own
    telecallers when the lead's store is known — never another store's, so
    with nobody free there the team leader keeps it — else anyone on the team
    leader's team."""
    from .night_queue import queued_counts
    if store is not None:
        team = await store_telecallers(db, store)
    else:
        team = [u for u in await team_telecallers(db, tl) if u.available_for_leads is not False]
    if not team:
        return None
    start, end = ist_day_bounds_utc(ist_today())
    counts = dict((await db.execute(
        select(TeleCallLead.owner_user_id, func.count(TeleCallLead.id))
        .where(TeleCallLead.owner_user_id.in_([u.id for u in team]),
               TeleCallLead.assigned_at >= start, TeleCallLead.assigned_at < end)
        .group_by(TeleCallLead.owner_user_id))).all())
    queued = await queued_counts(db, [u.id for u in team])
    return sorted(team, key=lambda u: (counts.get(u.id, 0) + queued.get(u.id, 0), u.id))[0]


async def team_telecallers(db: AsyncSession, tl: User) -> list[User]:
    """Active telecallers on this team leader's team: report to them, or
    share one of their city sheets."""
    tl_sheets = list((await db.execute(select(TeleSheetAssignment.sheet_tl_name)
                                       .where(TeleSheetAssignment.user_id == tl.id))).scalars().all())
    q = (select(User).join(Role, Role.id == User.role_id)
         .where(Role.name == "Telecaller", User.is_active == True))  # noqa: E712
    candidates = list((await db.execute(q)).scalars().all())
    team = []
    for u in candidates:
        if u.team_leader_id == tl.id:
            team.append(u)
            continue
        if tl_sheets:
            mine = (await db.execute(select(TeleSheetAssignment.id).where(
                TeleSheetAssignment.user_id == u.id, TeleSheetAssignment.sheet_tl_name.in_(tl_sheets)))).first()
            if mine:
                team.append(u)
    return team


# Lead sheet that covers a whole state, where one does. Elsewhere each
# store has its own sheet, found by its name in the store text below.
STATE_TO_SHEET = {"karnataka": "Bangalore", "assam": "Guwahati", "delhi": "Delhi", "newdelhi": "Delhi"}


def pick_sheet(tl_sheets: list[str], state: str | None, region: str | None, store_text: str | None) -> str:
    if not tl_sheets:
        return "Website"
    for hint in (state, region):
        wanted = STATE_TO_SHEET.get(_norm(hint))
        if wanted in tl_sheets:
            return wanted
    text = _norm(store_text)
    for sheet in tl_sheets:  # e.g. store text mentions "Chennai" or "Bangalore"
        if _norm(sheet) and _norm(sheet) in text:
            return sheet
    return sorted(tl_sheets)[0]


def _amount(text: str) -> Decimal | None:
    try:
        return Decimal(re.sub(r"[^0-9.]", "", text)) if text else None
    except InvalidOperation:
        return None


async def ingest_website_lead(db: AsyncSession, payload: dict, *, remote_ip: str | None = None) -> dict:
    """Log the call; create the premium lead only for a paid booking."""
    now = utcnow()
    entry_ref = pick(payload, "entry_id") or pick(payload, "payment_ref")
    ext = f"website:{entry_ref}" if entry_ref else None

    def log(status: str, message: str, lead_id: int | None = None) -> LeadSubmission:
        sub = LeadSubmission(channel="website", external_ref=ext, status=status, message=message[:300],
                             payload=payload, lead_id=lead_id, remote_ip=remote_ip, received_at=now)
        db.add(sub)
        return sub

    name, phone = pick(payload, "full_name"), pick(payload, "phone")
    if not name or len(norm_phone(phone)) < 10:
        log("invalid", "Full name and a 10-digit mobile number are required")
        await db.commit()
        return {"ok": False, "status": "invalid", "detail": "full_name and phone (10+ digits) are required"}
    if not is_paid(payload):
        state, reason = pick(payload, "payment_status").lower() or "not paid", pick(payload, "payment_error")
        sub = log(FAILED_STATUS, f"Payment {state}{f': {reason}' if reason else ''} — kept under Failed payments, not a lead")
        store = await match_store(db, pick(payload, "store"), pick(payload, "store_id"))
        sub.store_id = store.id if store else None  # its store's team sees it under Failed payments
        await db.commit()
        return {"ok": True, "status": "saved_unpaid", "detail": "Saved under Failed payments (only paid bookings become leads)"}
    if ext:
        existing = (await db.execute(select(TeleCallLead.id).where(TeleCallLead.external_ref == ext))).scalar()
        if existing:
            log("duplicate", "Same entry sent again — lead already created", existing)
            await db.commit()
            return {"ok": True, "status": "duplicate", "lead_id": existing}

    automation = await get_automation(db)
    await ensure_go_live(db)
    store_text = pick(payload, "store")
    store = await match_store(db, store_text, pick(payload, "store_id"))
    tl = await _real_team_leader(db, store)
    tl_sheets = list((await db.execute(select(TeleSheetAssignment.sheet_tl_name)
                                       .where(TeleSheetAssignment.user_id == tl.id))).scalars().all()) if tl else []
    # A team leader can cover several city sheets; use the one for the
    # customer's state / the store's region, not simply the first one
    # (which put a Thrissur booking under "Chennai").
    home_sheet = pick_sheet(tl_sheets, pick(payload, "state"), store.region if store else None, store_text)
    brand, model = pick(payload, "brand"), pick(payload, "model")
    pref_date = pick(payload, "preferred_date")
    paid_at = parse_sheet_datetime(pick(payload, "paid_at")) or now

    lead = TeleCallLead(
        # City sheet = the team leader's city, so the lead also shows on their
        # existing pages; "Website" when the store has no team leader yet.
        sheet_tl_name=home_sheet, spreadsheet_id="",
        full_name=name[:200], phone=phone[:30], email=pick(payload, "email")[:200],
        lead_source="Website (₹99 paid)", source_channel="website", is_premium=True,
        created_time=to_ist(now).strftime("%Y-%m-%d %H:%M"), submitted_at=paid_at, created_at=now,
        status="", stage="paid_advance", priority="hot",
        store_id=store.id if store else None, preferred_store_text=store_text[:200] or None,
        customer_state=pick(payload, "state")[:100] or None, customer_country=pick(payload, "country")[:60] or None,
        phone_brand=brand[:60] or None, phone_model=(f"{brand} {model}".strip() if brand and brand.lower() not in model.lower() else model)[:100] or None,
        preferred_date=pref_date[:30] or None, appointment_date=pref_date[:30] or "",
        payment_ref=pick(payload, "payment_ref")[:120] or None, payment_amount=_amount(pick(payload, "amount")),
        paid_at=paid_at, external_ref=ext, remarks=pick(payload, "place")[:500], person_calling="",
        edited_by_user=True,
    )
    refresh_derived(lead)  # keeps paid_advance (forward-only) → Hot
    db.add(lead)
    await db.flush()
    add_activity(db, lead, "system", at=now, meta={"source": "website", "entry": entry_ref},
                 notes=f"Premium website booking — paid ₹{lead.payment_amount or 99}"
                       f"{f' (payment {lead.payment_ref})' if lead.payment_ref else ''}; preferred store: "
                       f"{store.name if store else (store_text or 'not given')}")

    alerts: list = []
    owner = await pick_telecaller(db, tl, store) if tl else None
    owner_id = owner.id if owner else (tl.id if tl else None)
    fallback_tl = None if owner_id else await fallback_team_leader(
        db, [store.name if store else None, store_text, pick(payload, "state")], pick(payload, "country"))
    if fallback_tl:
        tl, owner_id = fallback_tl, fallback_tl.id
    queued = bool(owner_id) and should_queue(now, automation)
    if queued:
        queue_lead(db, lead, owner or tl, now=now, automation=automation)
    elif owner_id:
        await transfer_ownership(db, lead, owner_id, source="auto", actor_id=None, now=now, automation=automation,
                                 reason=f"Website booking for {store.name if store else 'store'}"
                                        f"{' — store not matched, team leader of the area to assign' if fallback_tl else ''}"
                                        f"{'' if owner or fallback_tl else ' — no telecaller on the team, given to the team leader'}")
        create_followup(db, lead, kind="first_call", owner_id=owner_id, at=now, reason="Call the premium website lead",
                        due_at=add_working_minutes(now, automation["first_call_minutes"], automation["working_hours"]))
    recipients = set(await team_leader_ids(db, None, owner_id)) | ({tl.id} if tl else set())
    if owner_id:
        recipients.add(owner_id)
    if not owner_id:
        recipients |= set(await admin_ids(db))
    for rid in (set() if queued else recipients):  # a queued lead is announced when handed over
        await create_alert(db, recipient_id=rid, kind="premium_lead", level=1 if owner_id else 3, lead=lead,
                           title="New premium website lead (₹99 paid)" if owner_id else "Premium website lead needs an owner",
                           body=f"{lead.full_name} · {store.name if store else (store_text or 'no store')} · "
                                f"{lead.phone_model or 'model not given'}"
                                f"{'' if store else ' — store not matched, assign it from Leads'}",
                           dedupe_key=f"premium:{lead.id}:{rid}", out=alerts)

    appt_dt = parse_sheet_datetime(pref_date)
    if appt_dt:
        d = to_ist(appt_dt).date()
        db.add(TeleAppointment(lead_id=lead.id, store_id=store.id if store else None, source="website",
                               scheduled_at=appt_dt if (to_ist(appt_dt).hour or to_ist(appt_dt).minute) else from_ist(datetime.combine(d, time(0, 0))),
                               purpose=lead.phone_model or "Store visit", attendance="scheduled", created_at=now))

    from .notify import emit_notifications, notify_lead_queued, notify_new_lead
    notes = await notify_lead_queued(db, lead) if queued else await notify_new_lead(db, lead)
    log("created", f"Lead created{'' if store else ' (store not matched)'}{' — night queue' if queued else ''}", lead.id)
    await db.commit()
    from .engine import emit_alerts
    await emit_notifications(notes)  # first, so the browser skips a second popup for the same lead
    await emit_alerts(alerts)
    from ..whatsapp import auto as wa_auto
    wa_auto.schedule("booking", lead.id)  # WhatsApp A1 to the customer, A2 to the store
    return {"ok": True, "status": "created", "lead_id": lead.id, "store": store.name if store else None,
            "team_leader": tl.name if tl else None, "owner_user_id": owner_id}
