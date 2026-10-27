"""Automatic WhatsApp messages for CRM events, sent with the approved
templates (templates.py) to the numbers in Settings → WhatsApp → Numbers:

  A1 booking_received        → customer   a paid website booking arrived
  A2 store_priority_booking  → store      the same booking (its branch number)
  B1 telecaller_new_lead     → telecaller a lead was assigned to them
  B2 lead_not_attended       → team leader a lead's first call was escalated

Each runs in the background after the caller's commit, in its own session,
so WhatsApp can never slow down or break lead intake; a refusal by Meta is
logged in whatsapp_messages (Settings → WhatsApp → Sent messages). Each
template can be switched off ("whatsapp.auto"), and a lead never gets the
same message to the same number twice."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

logger = logging.getLogger(__name__)

AUTO_KEY = "whatsapp.auto"
AUTO_TEMPLATES = ("A1", "A2", "B1", "B2")
SOURCE_LABEL = {"website": "Website", "facebook": "Facebook", "instagram": "Instagram", "meta_sheet": "Meta"}
COUNTRY_CODE = {"india": "91", "uae": "971", "unitedarabemirates": "971", "oman": "968", "qatar": "974",
                "bahrain": "973", "uk": "44", "unitedkingdom": "44", "malaysia": "60"}

_tasks: set[asyncio.Task] = set()  # keep a reference so a running send isn't garbage-collected
ENABLED = True  # tests switch background sending off (tests/conftest.py)


async def auto_settings(db) -> dict[str, bool]:
    """Which automatic messages are on (all on unless switched off)."""
    from ..crm.config import _get_json
    saved = await _get_json(db, AUTO_KEY) or {}
    return {k: bool(saved.get(k, True)) for k in AUTO_TEMPLATES}


async def save_auto_settings(db, value: dict, user_id: int | None) -> dict[str, bool]:
    from ..crm.config import _set_json
    merged = {**await auto_settings(db), **{k: bool(v) for k, v in value.items() if k in AUTO_TEMPLATES}}
    await _set_json(db, AUTO_KEY, merged, user_id)
    return merged


def customer_phone(phone: str, country: str | None) -> str:
    """The customer's number in international form; a local 10-digit number
    takes the code of the booking's country (India when not given)."""
    import re
    from .config import normalize_phone
    digits = re.sub(r"\D", "", phone or "")
    code = COUNTRY_CODE.get(re.sub(r"[^a-z]", "", (country or "").lower()))
    if code and code != "91" and len(digits) in (8, 9, 10) and not digits.startswith(code):
        return code + digits.lstrip("0")
    return normalize_phone(phone)


def _date(text: str | None) -> tuple[str, str]:
    """("29 Oct 2026", "11:00 AM" or "To be confirmed") from a preferred date."""
    from ..crm.timeutil import parse_sheet_datetime, to_ist
    if not text:
        return "To be confirmed", "To be confirmed"
    dt = parse_sheet_datetime(text)
    if dt is None:
        return text[:30], "To be confirmed"
    ist = to_ist(dt)
    has_time = ist.hour or ist.minute
    return ist.strftime("%d %b %Y"), (ist.strftime("%I:%M %p").lstrip("0") if has_time else "To be confirmed")


_meta_cache: dict = {"at": 0.0, "buttons": {}}


async def _approved_buttons(cfg, name: str, language: str) -> list[dict] | None:
    """The buttons the template really has on Meta (cached 10 minutes), or
    None when that can't be read. A template approved without the button the
    app knows about (e.g. B1 without its "View Lead" link) must be sent
    without it — Meta refuses a value for a button it doesn't have."""
    import time
    from .client import WhatsAppError, list_templates, meta_buttons
    if not cfg.waba_id:
        return None
    if time.monotonic() - _meta_cache["at"] > 600:
        try:
            rows = await list_templates(cfg)
        except WhatsAppError as e:
            logger.warning("Could not read WhatsApp templates from Meta: %s", e)
            return None
        _meta_cache.update(at=time.monotonic(),
                           buttons={(t.get("name"), t.get("language")): meta_buttons(t) for t in rows})
    return _meta_cache["buttons"].get((name, language))


def _buttons_to_send(tpl: dict, approved: list[dict] | None) -> set[int] | None:
    """Indexes of the app's buttons that the approved template has (a link
    only when it takes a value); None = unknown, send the usual ones."""
    if approved is None:
        return None
    kinds = {"url": "URL", "quick_reply": "QUICK_REPLY", "flow": "FLOW"}
    return {i for i, b in enumerate(tpl["buttons"])
            if i < len(approved) and approved[i]["type"] == kinds.get(b["type"])
            and (b["type"] != "url" or approved[i]["dynamic"])}


def schedule(job: str, lead_id: int, user_id: int | None = None) -> None:
    """Send in the background (call after the lead is committed)."""
    if not ENABLED:
        return
    try:
        task = asyncio.get_running_loop().create_task(run(job, lead_id, user_id))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run(job: str, lead_id: int, user_id: int | None = None) -> list[str]:
    """One job: "booking" (A1 + A2), "new_lead" (B1 to user_id) or
    "not_attended" (B2 to the team leader user_id). Returns what was sent."""
    from ...db.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            return await _run(db, job, lead_id, user_id)
    except Exception:  # never let a background send crash anything
        logger.exception("WhatsApp %s for lead %s failed", job, lead_id)
        return []


async def _run(db, job: str, lead_id: int, user_id: int | None = None) -> list[str]:
    from ...models.models import Store, TeleCallLead, User, WhatsAppContact, WhatsAppMessage
    from ..crm.timeutil import to_ist
    from .client import WhatsAppError, send_template
    from .config import get_config, valid_phone
    from .templates import build_components, get_template

    cfg = await get_config(db)
    if not cfg.active:
        return []
    switched = await auto_settings(db)
    lead = await db.get(TeleCallLead, lead_id)
    if lead is None:
        return []
    store = await db.get(Store, lead.store_id) if lead.store_id else None
    store_name = store.name if store else (lead.preferred_store_text or lead.sheet_tl_name or "Break Protection")
    model = lead.phone_model or lead.phone_brand or "Not given"
    received = to_ist(lead.submitted_at or lead.created_at or datetime.utcnow()).strftime("%d %b %Y, %I:%M %p")
    sent: list[str] = []

    async def send(key: str, to: str, values: dict, buttons: dict | None = None) -> None:
        if not switched.get(key) or not to or not valid_phone(to):
            return
        tpl = await get_template(db, key)
        purpose = f"auto:{key}"
        dup = (await db.execute(select(WhatsAppMessage.id).where(
            WhatsAppMessage.lead_id == lead.id, WhatsAppMessage.purpose == purpose,
            WhatsAppMessage.to_phone == to, WhatsAppMessage.status != "failed"))).first()
        if dup:
            return
        try:
            include = _buttons_to_send(tpl, await _approved_buttons(cfg, tpl["name"], tpl["language"]))
            components = build_components(tpl, {k: str(v) for k, v in values.items()}, buttons,
                                          include_buttons=include, payload_prefix=f"lead{lead.id}")
            await send_template(db, cfg, to=to, template=tpl["name"], language=tpl["language"],
                                components=components, params={"values": values, "buttons": buttons or {}},
                                purpose=purpose, sent_by=None, lead_id=lead.id)
            sent.append(f"{key}:{to}")
        except (WhatsAppError, ValueError) as e:  # logged as failed by send_template / bad values
            logger.warning("WhatsApp %s to %s for lead %s not sent: %s", key, to, lead.id, e)

    async def contact(role: str, **where) -> list[str]:
        q = select(WhatsAppContact.phone, WhatsAppContact.store_id).where(WhatsAppContact.role == role)
        for k, v in where.items():
            q = q.where(getattr(WhatsAppContact, k) == v)
        return list((await db.execute(q)).all())

    if job == "booking":
        booking_date, slot = _date(lead.preferred_date or lead.appointment_date)
        name = (lead.full_name or "Customer").split()[0] if lead.full_name else "Customer"
        await send("A1", customer_phone(lead.phone, lead.customer_country), {
            "customer_name": name, "booking_date": booking_date, "time_slot": slot,
            "mobile_model": model, "store_name": store_name})
        if store:
            for phone, _ in await contact("store", store_id=store.id):
                await send("A2", phone, {
                    "customer_name": lead.full_name or "Customer", "customer_number": lead.phone or "-",
                    "mobile_model": model, "booking_date": booking_date, "time_slot": slot})
    elif job == "new_lead" and user_id:
        rows = await contact("telecaller", user_id=user_id)
        # the row for this lead's store, else the "any store" row, else any row of theirs
        phone = next((p for p, s in rows if store and s == store.id), None) \
            or next((p for p, s in rows if s is None), None) or (rows[0][0] if rows else None)
        await send("B1", phone, {"lead_name": lead.full_name or "Customer",
                                 "lead_source": SOURCE_LABEL.get(lead.source_channel or "", lead.lead_source or "Lead"),
                                 "received_time": received}, {0: str(lead.id)})
    elif job == "not_attended" and user_id:
        owner = await db.get(User, lead.owner_user_id) if lead.owner_user_id else None
        for phone, _ in await contact("team_leader", user_id=user_id):
            await send("B2", phone, {"lead_name": lead.full_name or "Customer",
                                     "lead_source": SOURCE_LABEL.get(lead.source_channel or "", lead.lead_source or "Lead"),
                                     "telecaller_name": owner.name if owner else "Unassigned",
                                     "received_time": received}, {0: str(lead.id)})
    return sent
