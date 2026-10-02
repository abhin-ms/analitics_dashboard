"""Meta Lead Ads (Facebook / Instagram lead forms) → CRM leads.

The webhook only says "lead <id> arrived on form <id>"; the lead itself
(answers, ad, ad set, campaign, platform) is read from the Graph API with
the system-user token. Every submission is kept in meta_leads.

Branch: the lead form → store mapping (meta_form_stores). A form seen for
the first time is matched by its ad set / form name ("Hitech City West -
18 September 2026 - OTP Verify" → store "Hitech City West"); admins can set
or correct it. Routing is the website path: store → its team leader → one
of that team leader's telecallers. No store or no team leader → unassigned
and admins are alerted.

Hot: Meta has no payment, but the form asks whether the customer accepts
the ₹99 pre-booking fee; "yes" makes the lead Hot (not premium — that badge
stays for paid website bookings).

The same Meta leads also reach the CRM through the city Google Sheets. The
two are merged on phone number + submission time (within a day), whichever
arrives first: a sheet row attaches to the webhook lead (tele_call_sync),
and a webhook lead arriving after the sheet row enriches that row instead
of creating a second lead.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...models.models import MetaFormStore, MetaLead, Store, TeleCallLead, TeleSheetAssignment, User
from .config import ensure_go_live, get_automation
from .engine import (
    add_activity, admin_ids, create_alert, create_followup, emit_alerts, norm_phone, refresh_derived,
    transfer_ownership,
)
from .intake import _real_team_leader, match_store, pick_sheet, pick_telecaller
from .notify import emit_notifications, notify_new_lead
from .timeutil import add_working_minutes, parse_sheet_datetime, to_ist, utcnow

logger = logging.getLogger(__name__)

LEAD_FIELDS = ("id,created_time,field_data,form_id,ad_id,ad_name,adset_id,adset_name,"
               "campaign_id,campaign_name,platform,is_organic")
PLATFORMS = {"fb": "facebook", "ig": "instagram", "facebook": "facebook", "instagram": "instagram"}
MERGE_WINDOW = timedelta(days=1)
DEFAULT_SHEET = "Meta"  # city label for leads whose store has no team leader yet

_page_tokens: dict[str, str] = {}
_form_names: dict[str, str] = {}


# ── Graph API ──────────────────────────────────────────────────────
class MetaApiError(Exception):
    pass


async def graph_get(path: str, token: str, params: dict | None = None) -> dict:
    url = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, params={**(params or {}), "access_token": token})
    data = r.json() if r.content else {}
    if r.status_code != 200 or "error" in data:
        msg = (data.get("error") or {}).get("message") or f"HTTP {r.status_code}"
        raise MetaApiError(msg)
    return data


async def page_token(page_id: str) -> str:
    """Page access token derived from the system-user token (lead reads need
    a Page token on the new Pages experience). Cached per page."""
    if not settings.META_ACCESS_TOKEN:
        raise MetaApiError("META_ACCESS_TOKEN is not set on the server")
    if page_id not in _page_tokens:
        data = await graph_get(page_id, settings.META_ACCESS_TOKEN, {"fields": "access_token"})
        _page_tokens[page_id] = data.get("access_token") or settings.META_ACCESS_TOKEN
    return _page_tokens[page_id]


async def fetch_lead(leadgen_id: str, page_id: str) -> dict:
    try:
        return await graph_get(leadgen_id, await page_token(page_id), {"fields": LEAD_FIELDS})
    except MetaApiError:
        _page_tokens.pop(page_id, None)  # token may have been rotated: fetch a fresh one next time
        raise


async def fetch_form_name(form_id: str, page_id: str) -> str:
    if form_id not in _form_names:
        try:
            _form_names[form_id] = (await graph_get(form_id, await page_token(page_id), {"fields": "name"})).get("name", "")
        except MetaApiError as e:
            logger.warning("Could not read Meta form %s name: %s", form_id, e)
            return ""
    return _form_names[form_id]


# ── answers ────────────────────────────────────────────────────────
def _field_key(name: str) -> str:
    return re.sub(r"\s+", "_", (name or "").strip().strip('"').lower())


def _pretty(value: str) -> str:
    text = value.replace("_/_", " / ").replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def parse_answers(field_data: list[dict]) -> dict:
    """Pick the values the CRM uses out of Meta's field_data."""
    out = {"full_name": "", "phone": "", "email": "", "city": "", "brand": "", "prebook": "", "verified": None}
    for f in field_data or []:
        key, values = _field_key(f.get("name", "")), f.get("values") or [""]
        value = str(values[0] or "").strip()
        if key in ("full_name", "name"):
            out["full_name"] = value
        elif key in ("phone_number", "phone", "mobile_number"):
            out["phone"] = value
        elif key == "email":
            out["email"] = value
        elif key == "city":
            out["city"] = value
        elif "brand" in key:
            out["brand"] = _pretty(value)
        elif "pre-booking" in key or "pre_booking" in key or "99" in key:
            out["prebook"] = value.lower()
        elif key == "phone_number_verified":
            out["verified"] = value.lower() == "true"
    return out


# ── branch ─────────────────────────────────────────────────────────
_MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE = re.compile(rf"\b\d{{1,2}}\s*{_MONTHS}(\s*\d{{4}})?|\b{_MONTHS}\s*\d{{1,2}}(,?\s*\d{{4}})?|\b\d{{4}}\b", re.I)
_NOISE = {"bnp", "bnp1", "bnp2", "leads", "lead", "forms", "form", "final", "new", "copy", "phone", "phon", "number",
          "otp", "verify", "whatsapp", "broad", "store", "instant", "english"}


def candidate_names(name: str | None) -> list[str]:
    """Possible store names in an ad set / form name, most specific first:
    the whole name without dates and filler words, then each part."""
    if not name:
        return []
    text = _DATE.sub(" ", name)
    parts = []
    for seg in re.split(r"[|,\-_]+", text):
        words = [w for w in re.split(r"\s+", seg.strip()) if w and w.lower().strip(".") not in _NOISE]
        if words:
            parts.append(" ".join(words))
    out = [" ".join(parts)] + parts if len(parts) > 1 else parts
    return list(dict.fromkeys(p for p in out if len(p) >= 3))


async def resolve_store(db: AsyncSession, form_id: str, page_id: str, adset_name: str) -> tuple[Store | None, str]:
    """(store, form name). Uses the saved form mapping; a new form is
    matched once by name and the result saved (store or none) for admins."""
    mapping = (await db.execute(select(MetaFormStore).where(MetaFormStore.form_id == form_id))).scalar_one_or_none() \
        if form_id else None
    if mapping:
        store = await db.get(Store, mapping.store_id) if mapping.store_id else None
        return (store if store and store.is_active else None), mapping.form_name or ""
    form_name = await fetch_form_name(form_id, page_id) if form_id else ""
    store = None
    for cand in candidate_names(adset_name) + candidate_names(form_name):
        store = await match_store(db, cand, "")
        if store:
            break
    if form_id:
        db.add(MetaFormStore(form_id=form_id, form_name=(form_name or adset_name or "")[:200],
                             store_id=store.id if store else None, match_source="auto" if store else None,
                             updated_at=utcnow()))
        await db.flush()
    return store, form_name


# ── merge with the Google Sheet copy ───────────────────────────────
async def find_sheet_twin(db: AsyncSession, phone: str, at: datetime | None) -> TeleCallLead | None:
    """The same Meta lead already imported from a city sheet."""
    ph = norm_phone(phone)
    if len(ph) < 10 or at is None:
        return None
    rows = (await db.execute(select(TeleCallLead).where(
        TeleCallLead.spreadsheet_id != "", TeleCallLead.spreadsheet_id.isnot(None),
        TeleCallLead.submitted_at >= at - MERGE_WINDOW, TeleCallLead.submitted_at <= at + MERGE_WINDOW,
    ))).scalars().all()
    rows = [r for r in rows if norm_phone(r.phone) == ph]
    if not rows:
        return None
    linked = set((await db.execute(select(MetaLead.lead_id).where(
        MetaLead.lead_id.in_([r.id for r in rows])))).scalars().all())
    free = [r for r in rows if r.id not in linked]
    return min(free, key=lambda r: abs((r.submitted_at - at).total_seconds())) if free else None


def _source_label(platform: str) -> str:
    return {"instagram": "Instagram", "facebook": "Facebook"}.get(platform, "Meta")


# ── intake ─────────────────────────────────────────────────────────
async def ingest_meta_lead(db: AsyncSession, change: dict, *, lead_data: dict | None = None) -> dict:
    """One leadgen event → MetaLead row and a CRM lead (new, or merged with
    the sheet copy). Safe to call again for the same lead (Meta retries)."""
    now = utcnow()
    leadgen_id = str(change.get("leadgen_id") or (lead_data or {}).get("id") or "")
    page_id = str(change.get("page_id") or settings.META_PAGE_ID or "")
    if not leadgen_id:
        return {"ok": False, "status": "invalid", "detail": "no leadgen_id"}

    row = (await db.execute(select(MetaLead).where(MetaLead.leadgen_id == leadgen_id))).scalar_one_or_none()
    if row and row.status != "error":
        return {"ok": True, "status": "duplicate", "lead_id": row.lead_id}
    if not row:
        row = MetaLead(leadgen_id=leadgen_id, page_id=page_id, form_id=str(change.get("form_id") or "") or None,
                       ad_id=str(change.get("ad_id") or "") or None, received_at=now)
        db.add(row)

    try:
        data = lead_data or await fetch_lead(leadgen_id, page_id)
    except (MetaApiError, httpx.HTTPError) as e:
        row.status, row.error = "error", f"Could not read the lead from Meta: {e}"[:300]
        await db.commit()
        logger.error("Meta lead %s: %s", leadgen_id, row.error)
        return {"ok": False, "status": "error", "detail": row.error}

    ans = parse_answers(data.get("field_data") or [])
    platform = PLATFORMS.get(str(data.get("platform") or "").lower(), "facebook")
    created = parse_sheet_datetime(data.get("created_time")) or now
    row.form_id = str(data.get("form_id") or row.form_id or "") or None
    for attr in ("ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name"):
        if data.get(attr):
            setattr(row, attr, str(data[attr])[:200])
    row.platform, row.is_organic = platform, data.get("is_organic")
    row.full_name, row.phone, row.email = ans["full_name"][:200], ans["phone"][:30], ans["email"][:200]
    row.city, row.phone_brand = ans["city"][:100] or None, ans["brand"][:60] or None
    row.prebook_answer, row.phone_verified = ans["prebook"][:20] or None, ans["verified"]
    row.is_hot = ans["prebook"] == "yes"
    row.field_data, row.meta_created_at, row.error = data.get("field_data"), created, None

    store, form_name = await resolve_store(db, row.form_id or "", page_id, row.adset_name or "")
    row.form_name = (form_name or row.form_name or "")[:200] or None
    row.store_id = store.id if store else None
    branch_text = (row.adset_name or form_name or "")[:200]
    source = _source_label(platform)
    hot_note = "; answered YES to the ₹99 pre-booking question → Hot" if row.is_hot else ""

    twin = await find_sheet_twin(db, ans["phone"], created)
    if twin:
        # Already in the CRM from the city sheet: add what only Meta knows.
        twin.source_channel = platform
        twin.store_id = twin.store_id or (store.id if store else None)
        twin.preferred_store_text = twin.preferred_store_text or branch_text or None
        twin.phone_brand = twin.phone_brand or row.phone_brand
        twin.external_ref = twin.external_ref or f"meta:{leadgen_id}"
        if row.is_hot and not twin.priority_manual:
            twin.priority, twin.priority_manual = "hot", True
        add_activity(db, twin, "system", at=now, meta={"source": "meta", "leadgen_id": leadgen_id},
                     notes=f"{source} lead form ({branch_text or 'form'}){hot_note}")
        row.status, row.lead_id = "merged", twin.id
        return await _finish(db, row, [], [], {"ok": True, "status": "merged", "lead_id": twin.id})

    automation = await get_automation(db)
    await ensure_go_live(db)
    tl = await _real_team_leader(db, store)
    tl_sheets = list((await db.execute(select(TeleSheetAssignment.sheet_tl_name)
                                       .where(TeleSheetAssignment.user_id == tl.id))).scalars().all()) if tl else []
    sheet = pick_sheet(tl_sheets, ans["city"], store.region if store else None, branch_text) if tl_sheets else DEFAULT_SHEET

    lead = TeleCallLead(
        sheet_tl_name=sheet, spreadsheet_id="",
        full_name=ans["full_name"][:200] or "(no name)", phone=ans["phone"][:30], email=ans["email"][:200],
        lead_source=f"{source} lead form", source_channel=platform, is_premium=False,
        created_time=to_ist(created).strftime("%Y-%m-%d %H:%M"), submitted_at=created, created_at=now,
        status="", stage="new",
        # Hot is kept through status changes (priority is otherwise derived
        # from the stage, which would turn it back to Warm).
        priority="hot" if row.is_hot else None, priority_manual=bool(row.is_hot),
        store_id=store.id if store else None, preferred_store_text=branch_text or None,
        phone_brand=row.phone_brand, remarks=ans["city"][:500], person_calling="",
        external_ref=f"meta:{leadgen_id}", edited_by_user=False,
    )
    refresh_derived(lead)
    db.add(lead)
    await db.flush()
    add_activity(db, lead, "system", at=now, meta={"source": "meta", "leadgen_id": leadgen_id, "ad": row.ad_name},
                 notes=f"{source} lead form · {branch_text or 'unknown form'}"
                       f"{f' · ad: {row.ad_name}' if row.ad_name else ''}{hot_note}")

    alerts: list = []
    owner = await pick_telecaller(db, tl) if tl else None
    owner_id = owner.id if owner else (tl.id if tl else None)
    if owner_id:
        await transfer_ownership(db, lead, owner_id, source="auto", actor_id=None, now=now, automation=automation,
                                 reason=f"{source} lead for {store.name}"
                                        f"{'' if owner else ' — no telecaller on the team, given to the team leader'}")
        create_followup(db, lead, kind="first_call", owner_id=owner_id, at=now,
                        reason=f"Call the new {'HOT ' if row.is_hot else ''}{source} lead",
                        due_at=add_working_minutes(now, automation["first_call_minutes"], automation["working_hours"]))
    if not owner_id:
        for rid in await admin_ids(db):
            await create_alert(db, recipient_id=rid, kind="unassigned", level=3, lead=lead,
                               title=f"{source} lead needs an owner",
                               body=f"{lead.full_name} · {branch_text or 'unknown form'} — "
                                    f"{'store has no team leader' if store else 'form not matched to a store'}. "
                                    f"Map the form in CRM Settings → Integrations, or assign from Leads.",
                               dedupe_key=f"meta_unassigned:{lead.id}:{rid}", out=alerts)

    notes = await notify_new_lead(db, lead)  # owner / branch team, or everyone if unassigned
    row.status, row.lead_id = "created", lead.id
    return await _finish(db, row, alerts, notes, {"ok": True, "status": "created", "lead_id": lead.id,
                                           "store": store.name if store else None,
                                           "team_leader": tl.name if tl else None, "owner_user_id": owner_id,
                                           "hot": bool(row.is_hot), "platform": platform})


async def _finish(db: AsyncSession, row: MetaLead, alerts: list, notes: list, result: dict) -> dict:
    try:
        await db.commit()
    except IntegrityError:  # the same lead delivered twice at once
        await db.rollback()
        existing = (await db.execute(select(MetaLead.lead_id).where(MetaLead.leadgen_id == row.leadgen_id))).scalar()
        return {"ok": True, "status": "duplicate", "lead_id": existing}
    await emit_notifications(notes)  # first, so the browser skips a second popup for the same lead
    await emit_alerts(alerts)
    try:
        from ...socket import sio
        await sio.emit("data:refresh", {"section": "tele_call_leads"})
    except Exception as e:
        logger.warning("Failed to emit socket refresh: %s", e)
    return result


# ── after an admin maps a form ─────────────────────────────────────
async def route_unassigned_for_form(db: AsyncSession, form_id: str, actor: User) -> int:
    """Give the form's still-unassigned, untouched leads to the new store's team."""
    mapping = (await db.execute(select(MetaFormStore).where(MetaFormStore.form_id == form_id))).scalar_one_or_none()
    store = await db.get(Store, mapping.store_id) if mapping and mapping.store_id else None
    tl = await _real_team_leader(db, store)
    if not tl:
        return 0
    now, automation = utcnow(), await get_automation(db)
    leads = (await db.execute(
        select(TeleCallLead).join(MetaLead, MetaLead.lead_id == TeleCallLead.id)
        .where(MetaLead.form_id == form_id, MetaLead.status == "created", TeleCallLead.owner_user_id.is_(None))
    )).scalars().all()
    for lead in leads:
        lead.store_id = store.id
        owner = await pick_telecaller(db, tl)
        await transfer_ownership(db, lead, (owner or tl).id, source="manual", actor_id=actor.id, now=now,
                                 automation=automation, reason=f"Form mapped to {store.name}")
        if not lead.status:
            create_followup(db, lead, kind="first_call", owner_id=(owner or tl).id, at=now,
                            reason="Call the Meta lead",
                            due_at=add_working_minutes(now, automation["first_call_minutes"], automation["working_hours"]))
    return len(leads)


# ── catch-up (missed webhooks, first setup) ────────────────────────
async def backfill(db: AsyncSession, since: datetime, page_id: str | None = None) -> dict:
    """Read every form's leads created after `since` and ingest the ones not
    seen yet. Leads already in the CRM from a sheet are merged, not doubled."""
    page_id = page_id or settings.META_PAGE_ID
    if not page_id:
        raise MetaApiError("META_PAGE_ID is not set on the server")
    token = await page_token(page_id)
    stats = {"forms": 0, "seen": 0, "created": 0, "merged": 0, "duplicate": 0, "error": 0}
    forms = (await graph_get(f"{page_id}/leadgen_forms", token, {"fields": "id,leads_count", "limit": 200})).get("data", [])
    ts = int((since - datetime(1970, 1, 1)).total_seconds())
    flt = f'[{{"field":"time_created","operator":"GREATER_THAN","value":{ts}}}]'
    for form in forms:
        if not form.get("leads_count"):
            continue
        stats["forms"] += 1
        after = None
        while True:
            params = {"fields": LEAD_FIELDS, "filtering": flt, "limit": 100, **({"after": after} if after else {})}
            page = await graph_get(f"{form['id']}/leads", token, params)
            for item in page.get("data", []):
                stats["seen"] += 1
                res = await ingest_meta_lead(db, {"leadgen_id": item["id"], "page_id": page_id,
                                                  "form_id": item.get("form_id") or form["id"]}, lead_data=item)
                stats[res["status"]] = stats.get(res["status"], 0) + 1
            after = (page.get("paging") or {}).get("cursors", {}).get("after") if (page.get("paging") or {}).get("next") else None
            if not after:
                break
    return stats
