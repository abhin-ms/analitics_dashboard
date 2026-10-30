"""₹99 payment a telecaller asks for after a call — two ways:

Settings (Settings → WhatsApp → Payments, payment_settings.py) are loaded
from the database at the start of every request that uses them (load()).

* Pay inside WhatsApp (mode "whatsapp", the default for Indian numbers when
  the WhatsApp payment configuration is set): template A7 (payment_request) with Meta's
  "Review and Pay" button carrying the order (₹99, our Razorpay payment
  configuration, a reference). The customer pays by UPI without leaving
  WhatsApp; WhatsApp reports it on its webhook (statuses of type
  "payment"), and every report is confirmed with Meta's payment lookup
  before the lead is marked paid. Razorpay's payment.captured webhook
  (notes.payment_link) is a second way in.
* Payment link (mode "link"):

Send: the telecaller checks the form (filled from the lead), a Razorpay
payment link is created for that lead and the WhatsApp template A6
(payment_link) goes to the customer with a Pay button. The button opens
our own short link (/api/v1/public/pay/<token>), which notes the open and
goes on to Razorpay's payment page.

Paid: Razorpay calls /api/v1/public/razorpay/webhook (payment_link.paid);
the link is marked paid, the lead becomes Paid Advance (Hot), the visit is
booked when a time was given, the customer gets "Booking received" and the
store its booking message, and the telecaller, their team leader and the
admins are told. Expired / cancelled links come the same way, and a sweep
in the automation tick asks Razorpay about links past their expiry in case
a webhook was missed.

Only these leads count as "paid via call"; website bookings are paid on the
website (TeleCallLead.is_premium) and are never in this table."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import PaymentLink, Store, TeleAppointment, TeleCallLead, User
from .engine import add_activity, admin_ids, create_alert, mark_edited, refresh_derived, team_leader_ids
from .payment_settings import PaySettings, get_pay_settings
from .timeutil import to_ist, utcnow

logger = logging.getLogger(__name__)

RZP_API = "https://api.razorpay.com/v1"
TEMPLATE_KEY = "A6"      # payment link (Pay button → Razorpay page)
WA_TEMPLATE_KEY = "A7"   # pay inside WhatsApp (Review and Pay)
OPEN = "sent"


class PaymentLinkError(Exception):
    pass


# The settings in use: refreshed from the database by load() at the start of
# each request / webhook / sweep, so every worker sees an admin's change.
_S = PaySettings()


async def load(db: AsyncSession) -> PaySettings:
    global _S
    _S = await get_pay_settings(db)
    return _S


def configured() -> bool:
    """Razorpay payment links can be made."""
    return bool(_S.key_id and _S.key_secret)


def whatsapp_pay_ready() -> bool:
    return bool(_S.whatsapp_config)


def modes() -> dict[str, bool]:
    return {"whatsapp": whatsapp_pay_ready(), "link": configured()}


def enabled() -> bool:
    return whatsapp_pay_ready() or configured()


def _indian(phone: str) -> bool:
    return phone.startswith("91") and len(phone) == 12


async def _rzp(method: str, path: str, json: dict | None = None) -> dict:
    """One Razorpay API call; a refusal becomes PaymentLinkError with its reason."""
    try:
        async with httpx.AsyncClient(timeout=20, auth=(_S.key_id, _S.key_secret)) as c:
            r = await c.request(method, f"{RZP_API}/{path}", json=json)
    except httpx.HTTPError as e:
        raise PaymentLinkError(f"Could not reach Razorpay: {e}") from e
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        raise PaymentLinkError((data.get("error") or {}).get("description") or f"Razorpay refused it ({r.status_code})")
    return data


def verify_signature(body: bytes, signature: str) -> bool:
    secret = _S.webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def fmt_visit(at: datetime | None) -> str:
    if not at:
        return "To be confirmed"
    ist = to_ist(at)
    return f"{ist.strftime('%a')} {ist.day} {ist.strftime('%b')}, {ist.strftime('%I:%M %p').lstrip('0')}"


def visit_parts(at: datetime | None) -> tuple[str, str]:
    """("Sat, 1 Nov 2026", "11:30 AM"): the date and time variables of A7."""
    if not at:
        return "To be confirmed", "To be confirmed"
    ist = to_ist(at)
    return f"{ist.strftime('%a')}, {ist.day} {ist.strftime('%b %Y')}", ist.strftime("%I:%M %p").lstrip("0")


# ── the form ───────────────────────────────────────────────────────
async def prefill(db: AsyncSession, lead: TeleCallLead) -> dict:
    """What the form opens with: everything the lead already says."""
    await load(db)
    from ..crm.timeutil import parse_sheet_datetime
    appt = (await db.execute(select(TeleAppointment).where(
        TeleAppointment.lead_id == lead.id, TeleAppointment.scheduled_at >= utcnow())
        .order_by(TeleAppointment.scheduled_at))).scalars().first()
    visit = appt.scheduled_at if appt else parse_sheet_datetime(lead.preferred_date or "")
    if visit and visit < utcnow():
        visit = None
    return {
        "customer_name": lead.full_name or "",
        "customer_phone": lead.phone or "",
        "phone_model": lead.phone_model or lead.phone_brand or "",
        "service": lead.service_type or "",
        "store_id": (appt.store_id if appt and appt.store_id else None) or lead.store_id,
        "visit_at": to_ist(visit).strftime("%Y-%m-%dT%H:%M") if visit else "",
        "amount": _S.amount,
        "valid_hours": _S.hours,
        "mode": "whatsapp" if whatsapp_pay_ready() else "link",
        "modes": modes(),
    }


def link_row(pl: PaymentLink, names: dict | None = None, stores: dict | None = None) -> dict:
    from ..crm.timeutil import iso_utc
    return {
        "id": pl.id, "lead_id": pl.lead_id, "status": pl.status, "amount": pl.amount, "mode": pl.mode,
        "customer_name": pl.customer_name, "customer_phone": pl.customer_phone,
        "phone_model": pl.phone_model, "service": pl.service,
        "store": (stores or {}).get(pl.store_id) if pl.store_id else None,
        "visit_at": iso_utc(pl.visit_at), "expires_at": iso_utc(pl.expires_at),
        "created_at": iso_utc(pl.created_at), "opened_at": iso_utc(pl.opened_at), "paid_at": iso_utc(pl.paid_at),
        "payment_id": pl.payment_id, "error": pl.error,
        "sent_by": (names or {}).get(pl.sent_by) if pl.sent_by else None, "sent_by_id": pl.sent_by,
    }


# ── send ───────────────────────────────────────────────────────────
async def send_link(db: AsyncSession, lead: TeleCallLead, user: User, form: dict) -> PaymentLink:
    """Create the Razorpay link and send it on WhatsApp. Device details and
    the store go back to the lead; the name and number are used for this
    link only (a sheet lead's own name and number follow its sheet)."""
    from ..crm.timeutil import from_ist
    from ..whatsapp import auto as wa_auto
    from ..whatsapp.client import WhatsAppError, send_template
    from ..whatsapp.config import get_config, valid_phone
    from ..whatsapp.templates import build_components, get_template

    await load(db)
    if not enabled():
        raise PaymentLinkError("Payments aren't set up yet: an admin can add them in Settings → WhatsApp → Payments")
    cfg = await get_config(db)
    if not cfg.active:
        raise PaymentLinkError("WhatsApp is not set up or turned off (Settings → WhatsApp)")
    name = (form.get("customer_name") or "").strip()[:200]
    to = wa_auto.customer_phone(form.get("customer_phone") or "", lead.customer_country)
    if not name:
        raise PaymentLinkError("Enter the customer's name")
    if not valid_phone(to):
        raise PaymentLinkError("Enter the customer's WhatsApp number with country code, e.g. 9198470 12345")
    mode = form.get("mode") or ("whatsapp" if whatsapp_pay_ready() and _indian(to) else "link")
    if mode == "whatsapp" and not whatsapp_pay_ready():
        raise PaymentLinkError("Pay inside WhatsApp isn't set up (WhatsApp payment configuration missing)")
    if mode == "whatsapp" and not _S.address_ready():
        raise PaymentLinkError("Pay inside WhatsApp needs the business address (Settings → WhatsApp → Payments)")
    if mode == "whatsapp" and not _indian(to):
        raise PaymentLinkError("Pay inside WhatsApp works for Indian (+91) numbers only — send a payment link instead")
    if mode == "link" and not configured():
        raise PaymentLinkError("Payment links aren't set up (Razorpay keys missing)")
    store = await db.get(Store, int(form["store_id"])) if form.get("store_id") else None
    visit_at = None
    if form.get("visit_at"):
        try:
            visit_at = from_ist(datetime.fromisoformat(str(form["visit_at"])))
        except ValueError:
            raise PaymentLinkError("Pick a valid visit date and time")
    now = utcnow()
    amount = int(_S.amount)

    # the lead keeps what was corrected
    for field, key in (("phone_model", "phone_model"), ("service_type", "service")):
        value = (form.get(key) or "").strip()[:120]
        if value and value != (getattr(lead, field) or ""):
            setattr(lead, field, value)
            mark_edited(lead, field)
    if store and lead.store_id != store.id:
        lead.store_id = store.id

    # one open link per lead: a new one replaces the last
    for old in (await db.execute(select(PaymentLink).where(
            PaymentLink.lead_id == lead.id, PaymentLink.status == OPEN))).scalars().all():
        try:
            if old.rzp_link_id and configured():
                await _rzp("POST", f"payment_links/{old.rzp_link_id}/cancel")
        except PaymentLinkError as e:
            logger.warning("Could not cancel payment link %s: %s", old.rzp_link_id, e)
        old.status = "cancelled"

    pl = PaymentLink(lead_id=lead.id, sent_by=user.id, token=secrets.token_hex(6), amount=amount, mode=mode,
                     status=OPEN, customer_name=name, customer_phone=to,
                     phone_model=(form.get("phone_model") or "").strip()[:120] or None,
                     service=(form.get("service") or "").strip()[:120] or None,
                     store_id=store.id if store else None, visit_at=visit_at,
                     expires_at=now + timedelta(hours=int(_S.hours)), created_at=now)
    db.add(pl)
    await db.flush()
    store_label = store.name if store else "Break Protection"
    values = {"customer_name": name.split()[0], "store_name": store_label,
              "mobile_model": pl.phone_model or "your phone", "visit_time": fmt_visit(visit_at)}
    if mode == "whatsapp":
        values["visit_date"], values["visit_time"] = visit_parts(visit_at)
        pl.reference_id = f"BP{pl.id}{pl.token[:8]}".upper()
        tpl = await get_template(db, WA_TEMPLATE_KEY)
        buttons = {0: order_details(pl, store_label, lead.id)}
    else:
        data = await _rzp("POST", "payment_links", {
            "amount": amount * 100, "currency": "INR", "accept_partial": False,
            "expire_by": int((pl.expires_at - datetime(1970, 1, 1)).total_seconds()),  # naive UTC → unix
            "reference_id": f"BPL{pl.id}",
            "description": f"Priority slot · {store_label}"[:2048],
            "customer": {"name": name, "contact": f"+{to}"},
            "notify": {"sms": False, "email": False}, "reminder_enable": False,
            "notes": {"lead_id": str(lead.id), "payment_link": str(pl.id), "sent_by": user.name},
        })
        pl.rzp_link_id, pl.short_url = data.get("id"), data.get("short_url")
        tpl = await get_template(db, TEMPLATE_KEY)
        values["amount"] = str(amount)
        buttons = {0: pl.token}

    approved = await wa_auto._approved_buttons(cfg, tpl["name"], tpl["language"])
    include = wa_auto._buttons_to_send(tpl, approved)
    if include is not None and 0 not in include:
        raise PaymentLinkError(f"The approved WhatsApp template {tpl['name']} has no "
                               f"{tpl['buttons'][0]['text']} button — check it in Meta")
    try:
        msg = await send_template(db, cfg, to=to, template=tpl["name"], language=tpl["language"],
                                  components=build_components(tpl, values, buttons, include_buttons={0},
                                                              payload_prefix=f"lead{lead.id}"),
                                  params={"values": values, "buttons": {0: pl.reference_id or pl.token}},
                                  purpose=f"auto:{tpl['key']}", sent_by=user.id, lead_id=lead.id)
    except WhatsAppError as e:
        pl.status, pl.error = "failed", f"WhatsApp: {e}"[:300]
        if pl.rzp_link_id:
            try:
                await _rzp("POST", f"payment_links/{pl.rzp_link_id}/cancel")
            except PaymentLinkError:
                pass
        await db.commit()
        raise PaymentLinkError(f"WhatsApp refused the message: {e}") from e
    pl.whatsapp_message_id = msg.id
    add_activity(db, lead, "payment", user_id=user.id, at=now, new_value="Link sent",
                 notes=f"₹{amount} {'Review and Pay request' if mode == 'whatsapp' else 'payment link'} sent on WhatsApp to +{to}"
                       f"{f' · visit {fmt_visit(visit_at)}' if visit_at else ''} · valid {_S.hours} h",
                 meta={"payment_link": pl.id})
    return pl


def order_details(pl: PaymentLink, store_label: str, lead_id: int) -> dict:
    """The order the Review and Pay button opens (Meta Payments API, India)."""
    paise = {"value": pl.amount * 100, "offset": 100}
    return {
        "reference_id": pl.reference_id, "type": "digital-goods",
        "payment_settings": [{"type": "payment_gateway", "payment_gateway": {
            "type": "razorpay", "configuration_name": _S.whatsapp_config,
            "razorpay": {"receipt": pl.reference_id,
                         "notes": {"lead_id": str(lead_id), "payment_link": str(pl.id)}}}}],
        "currency": "INR", "total_amount": paise,
        "order": {
            "status": "pending",
            "expiration": {"timestamp": str(int((pl.expires_at - datetime(1970, 1, 1)).total_seconds())),
                           "description": "This payment request has expired. Ask us for a new one."},
            # no product catalog, so Meta wants the origin and the importer on each item
            "items": [{"retailer_id": "priority-slot", "name": f"Priority slot · {store_label}"[:60],
                       "amount": paise, "quantity": 1, "country_of_origin": "India",
                       "importer_name": _S.business_name,
                       "importer_address": {"address_line1": _S.address_line1, "city": _S.city,
                                            **({"zone_code": _S.state} if _S.state else {}),
                                            "postal_code": _S.postal_code, "country_code": "IN"}}],
            "subtotal": paise, "tax": {"value": 0, "offset": 100},
        },
    }


async def _wa_lookup(db: AsyncSession, pl: PaymentLink) -> dict | None:
    """Meta's own record of a Review and Pay order (never trust a webhook alone)."""
    from ..whatsapp.client import WhatsAppError, _call
    from ..whatsapp.config import get_config
    cfg = await get_config(db)
    try:
        data = await _call(cfg, "GET", f"{cfg.phone_number_id}/payments/{_S.whatsapp_config}/{pl.reference_id}")
    except WhatsAppError as e:
        raise PaymentLinkError(f"Could not check the payment with WhatsApp: {e}") from e
    return ((data or {}).get("payments") or [None])[0]


async def _apply_wa_payment(db: AsyncSession, pl: PaymentLink, payment: dict | None) -> list:
    """A Review and Pay order as Meta reports it: captured → paid."""
    if not payment or payment.get("status") != "captured":
        return []
    txs = payment.get("transactions") or []
    ok = [t for t in txs if t.get("status") == "success"] or txs
    t = ok[-1] if ok else {}
    amount = (payment.get("amount") or {}).get("value")
    at = datetime.utcfromtimestamp(int(t["updated_timestamp"])) if t.get("updated_timestamp") else None
    return await mark_paid(db, pl, payment_id=t.get("pg_transaction_id") or t.get("id"),
                           amount=int(amount) // 100 if amount else None, at=at)


async def apply_whatsapp_payments(db: AsyncSession, cfg, payload: dict) -> tuple[list, list[int]]:
    """WhatsApp webhook: statuses of type "payment" for our Review and Pay
    orders. Each is confirmed with Meta's lookup before anything changes.
    Returns (alerts, leads that just got paid)."""
    await load(db)
    alerts: list = []
    paid: list[int] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            for st in (change.get("value") or {}).get("statuses", []) or []:
                if st.get("type") != "payment":
                    continue
                ref = (st.get("payment") or {}).get("reference_id")
                pl = (await db.execute(select(PaymentLink).where(PaymentLink.reference_id == ref))).scalar_one_or_none() \
                    if ref else None
                if pl is None or pl.status == "paid":
                    continue
                try:
                    new = await _apply_wa_payment(db, pl, await _wa_lookup(db, pl))
                except PaymentLinkError as e:
                    logger.warning("Payment %s not confirmed: %s", ref, e)
                    continue
                alerts += new
                if new:
                    paid.append(pl.lead_id)
    return alerts, paid


# ── paid / expired ─────────────────────────────────────────────────
async def mark_paid(db: AsyncSession, pl: PaymentLink, *, payment_id: str | None, amount: int | None,
                    at: datetime | None = None) -> list:
    """The customer paid: link, lead, visit, messages, alerts. Safe to call
    twice (Razorpay retries). Returns the alerts to emit after commit."""
    from .config import get_automation, get_go_live
    from .engine import set_status_from_app
    if pl.status == "paid":
        return []
    now = at or utcnow()
    pl.status, pl.payment_id, pl.paid_amount, pl.paid_at = "paid", payment_id, amount or pl.amount, now
    lead = await db.get(TeleCallLead, pl.lead_id)
    if lead is None:
        return []
    if pl.visit_at:
        has = (await db.execute(select(TeleAppointment.id).where(
            TeleAppointment.lead_id == lead.id, TeleAppointment.scheduled_at == pl.visit_at))).first()
        if not has:
            db.add(TeleAppointment(lead_id=lead.id, store_id=pl.store_id or lead.store_id, scheduled_at=pl.visit_at,
                                   purpose=pl.service or pl.phone_model or "Store visit", attendance="scheduled",
                                   source="payment_link", created_at=now))
        ist = to_ist(pl.visit_at)
        lead.preferred_date = ist.strftime("%Y-%m-%d %H:%M")  # the booking messages read the slot from here
        if (lead.status or "") != "Appointment":
            await set_status_from_app(db, lead, "Appointment", actor_id=pl.sent_by,
                                      automation=await get_automation(db), go_live=await get_go_live(db), now=now)
    if lead.stage not in ("converted",):
        lead.stage = "paid_advance"
    refresh_derived(lead)
    add_activity(db, lead, "payment", user_id=None, at=now, new_value="Paid",
                 notes=f"Customer paid ₹{pl.paid_amount} with the payment link"
                       f"{f' ({payment_id})' if payment_id else ''}", meta={"payment_link": pl.id})

    alerts: list = []
    who = {pl.sent_by, lead.owner_user_id} - {None}
    who |= set(await team_leader_ids(db, lead.sheet_tl_name, lead.owner_user_id or pl.sent_by))
    who |= set(await admin_ids(db))
    sender = await db.get(User, pl.sent_by) if pl.sent_by else None
    for uid in who:
        await create_alert(db, recipient_id=uid, kind="payment_paid", level=1, lead=lead,
                           title=f"{pl.customer_name or lead.full_name} paid ₹{pl.paid_amount}",
                           body=f"Payment link from {sender.name if sender else 'a telecaller'}"
                                f"{f' · visit {fmt_visit(pl.visit_at)}' if pl.visit_at else ''}",
                           dedupe_key=f"paylink:{pl.id}:{uid}", out=alerts)
    return alerts


async def after_paid(lead_id: int) -> None:
    """Booking messages: "Booking received" to the customer, the booking to
    the store (WhatsApp A1 + A2, as for a website booking)."""
    from ..whatsapp import auto as wa_auto
    wa_auto.schedule("booking", lead_id)
    try:
        await _close_wa_order(lead_id)
    except Exception:  # a courtesy message: never break the payment over it
        logger.exception("Order status for lead %s not sent", lead_id)


async def _close_wa_order(lead_id: int) -> None:
    """Review and Pay: mark the order completed in the customer's chat."""
    from ...db.session import AsyncSessionLocal
    from ..whatsapp.client import WhatsAppError, _call
    from ..whatsapp.config import get_config
    async with AsyncSessionLocal() as db:
        pl = (await db.execute(select(PaymentLink).where(
            PaymentLink.lead_id == lead_id, PaymentLink.status == "paid", PaymentLink.mode == "whatsapp")
            .order_by(PaymentLink.id.desc()))).scalars().first()
        if pl is None or not pl.reference_id:
            return
        cfg = await get_config(db)
        if not cfg.active:
            return
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": pl.customer_phone,
                "type": "interactive", "interactive": {
                    "type": "order_status",
                    "body": {"text": f"Payment received. Your priority slot is reserved"
                                     f"{f' for {fmt_visit(pl.visit_at)}' if pl.visit_at else ''}."},
                    "action": {"name": "review_order", "parameters": {
                        "reference_id": pl.reference_id,
                        "order": {"status": "completed", "description": "₹99 priority slot paid"}}}}}
        try:
            await _call(cfg, "POST", f"{cfg.phone_number_id}/messages", json=body)
        except WhatsAppError as e:
            logger.warning("Order status for %s refused: %s", pl.reference_id, e)


async def apply_status(db: AsyncSession, pl: PaymentLink, rzp: dict) -> list:
    """Bring our link in line with Razorpay's view of it."""
    status = rzp.get("status")
    if status == "paid":
        pays = [p for p in rzp.get("payments") or [] if p.get("status") in ("captured", "authorized", None)]
        p = pays[-1] if pays else {}
        at = datetime.utcfromtimestamp(p["created_at"]) if p.get("created_at") else None
        return await mark_paid(db, pl, payment_id=p.get("payment_id") or p.get("id"),
                               amount=int(p["amount"]) // 100 if p.get("amount") else None, at=at)
    if status in ("expired", "cancelled") and pl.status == OPEN:
        pl.status = status
        lead = await db.get(TeleCallLead, pl.lead_id)
        if lead:
            add_activity(db, lead, "payment", user_id=None, at=utcnow(), new_value=status.title(),
                         notes=f"Payment link {status} without payment", meta={"payment_link": pl.id})
    return []


async def handle_webhook(db: AsyncSession, event: dict) -> tuple[str, list]:
    """A Razorpay webhook call. Returns (what happened, alerts)."""
    await load(db)
    kind = event.get("event") or ""
    if kind == "payment.captured":
        pay = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
        link_id = str((pay.get("notes") or {}).get("payment_link") or "")
        pl = await db.get(PaymentLink, int(link_id)) if link_id.isdigit() else None
        if pl is None or pl.mode != "whatsapp" or pl.status == "paid":
            return "ignored", []
        if pl.reference_id:  # confirm with WhatsApp too when it can be reached
            try:
                looked = await _wa_lookup(db, pl)
                if looked and looked.get("status") != "captured":
                    return "not confirmed", []
            except PaymentLinkError:
                pass
        at = datetime.utcfromtimestamp(pay["created_at"]) if pay.get("created_at") else None
        return "paid", await mark_paid(db, pl, payment_id=pay.get("id"),
                                       amount=int(pay["amount"]) // 100 if pay.get("amount") else None, at=at)
    entity = ((event.get("payload") or {}).get("payment_link") or {}).get("entity") or {}
    pl = (await db.execute(select(PaymentLink).where(PaymentLink.rzp_link_id == entity.get("id")))).scalar_one_or_none() \
        if entity.get("id") else None
    if pl is None:
        return "ignored", []
    if kind == "payment_link.paid":
        pay = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
        at = datetime.utcfromtimestamp(pay["created_at"]) if pay.get("created_at") else None
        alerts = await mark_paid(db, pl, payment_id=pay.get("id"),
                                 amount=int(pay["amount"]) // 100 if pay.get("amount") else None, at=at)
        return "paid", alerts
    if kind in ("payment_link.expired", "payment_link.cancelled"):
        return kind.split(".")[1], await apply_status(db, pl, {"status": kind.split(".")[1]})
    return "ignored", []


async def refresh(db: AsyncSession, pl: PaymentLink) -> list:
    """Ask Razorpay where the link stands (the Refresh button, and the sweep)."""
    await load(db)
    if pl.status != OPEN:
        return []
    if pl.mode == "whatsapp":
        return await _apply_wa_payment(db, pl, await _wa_lookup(db, pl)) if pl.reference_id else []
    if not pl.rzp_link_id:
        return []
    return await apply_status(db, pl, await _rzp("GET", f"payment_links/{pl.rzp_link_id}"))


async def sweep(db: AsyncSession, now: datetime) -> list:
    """Links past their expiry that are still open: ask Razorpay (a missed
    webhook), else mark them expired."""
    alerts: list = []
    rows = (await db.execute(select(PaymentLink).where(
        PaymentLink.status == OPEN, PaymentLink.expires_at < now).limit(50))).scalars().all()
    if rows:
        await load(db)
    for pl in rows:
        try:
            alerts += await refresh(db, pl) if (pl.mode == "whatsapp" or configured()) else []
        except PaymentLinkError as e:
            logger.warning("Payment link %s check failed: %s", pl.id, e)
        if pl.status == OPEN and now - pl.expires_at > timedelta(hours=1):
            await apply_status(db, pl, {"status": "expired"})
    return alerts
