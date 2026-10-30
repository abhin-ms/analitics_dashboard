"""₹99 payment links sent after a call (services/crm/payment_links.py):
the form, sending, a lead's links, the reports by team leader and
telecaller, and the two public addresses — the customer's Pay button and
Razorpay's webhook."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, require_permission
from ...db.session import get_db
from ...models.models import PaymentLink, Role, Store, TeleCallLead, User, UserStoreAccess
from ...services.crm import payment_links as pay
from ...services.crm.engine import add_activity, emit_alerts, user_names
from ...services.crm.metrics import period_bounds
from ...services.crm.payment_settings import get_pay_settings, mask, save_pay_settings
from ...services.crm.scope import CrmScope
from ...services.crm.timeutil import ist_today, utcnow
from .crm import load_lead, require_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm", tags=["Payment links"])
public_router = APIRouter(prefix="/public", tags=["Payment links (public)"])


class PaymentLinkIn(BaseModel):
    customer_name: str
    customer_phone: str
    phone_model: Optional[str] = None
    service: Optional[str] = None
    store_id: Optional[int] = None
    visit_at: Optional[str] = None  # YYYY-MM-DDTHH:MM, IST
    mode: Optional[str] = None      # "whatsapp" (Review and Pay) | "link"; default: WhatsApp for +91 when set up


async def _store_names(db: AsyncSession, links) -> dict[int, str]:
    ids = {l.store_id for l in links if l.store_id}
    return dict((await db.execute(select(Store.id, Store.name).where(Store.id.in_(ids)))).all()) if ids else {}


@router.get("/leads/{lead_id}/payment-link")
async def payment_link_form(lead_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """The prefilled form and the lead's links so far, newest first."""
    scope = await require_scope(db, user)
    lead = await load_lead(db, lead_id, scope)
    await pay.load(db)
    links = (await db.execute(select(PaymentLink).where(PaymentLink.lead_id == lead.id)
                              .order_by(PaymentLink.id.desc()))).scalars().all()
    names, stores = await user_names(db, {l.sent_by for l in links}), await _store_names(db, links)
    return {"enabled": pay.enabled(), "modes": pay.modes(), "can_send": scope.can_edit_leads, "form": await pay.prefill(db, lead),
            "links": [pay.link_row(l, names, stores) for l in links]}


@router.post("/leads/{lead_id}/payment-link")
async def send_payment_link(lead_id: int, body: PaymentLinkIn, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    scope = await require_scope(db, user, "edit")
    lead = await load_lead(db, lead_id, scope)
    if body.mode not in (None, "whatsapp", "link"):
        raise HTTPException(status_code=400, detail="mode must be whatsapp or link")
    try:
        pl = await pay.send_link(db, lead, user, body.model_dump())
    except pay.PaymentLinkError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return {"ok": True, "link": pay.link_row(pl, {user.id: user.name}, await _store_names(db, [pl]))}


@router.post("/payment-links/{link_id}/refresh")
async def refresh_payment_link(link_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Ask Razorpay where a link stands (in case its webhook hasn't come)."""
    scope = await require_scope(db, user)
    pl = await db.get(PaymentLink, link_id)
    if pl is None:
        raise HTTPException(status_code=404, detail="Payment link not found")
    await load_lead(db, pl.lead_id, scope)
    try:
        alerts = await pay.refresh(db, pl)
    except pay.PaymentLinkError as e:
        raise HTTPException(status_code=400, detail=str(e))
    paid_now = bool(alerts) or pl.status == "paid"
    await db.commit()
    await emit_alerts(alerts)
    if alerts:
        await pay.after_paid(pl.lead_id)
    names = await user_names(db, {pl.sent_by})
    return {"ok": True, "paid": paid_now, "link": pay.link_row(pl, names, await _store_names(db, [pl]))}


# ── settings (Settings → WhatsApp → Payments) ─────────────────────
class PaySettingsIn(BaseModel):
    whatsapp_config: Optional[str] = None
    key_id: Optional[str] = None
    key_secret: Optional[str] = None       # blank = keep the saved one
    webhook_secret: Optional[str] = None   # blank = keep the saved one
    clear_key_secret: bool = False
    clear_webhook_secret: bool = False
    amount: Optional[int] = None
    hours: Optional[int] = None


def _settings_view(s) -> dict:
    from ...core.config import settings as env
    return {
        "whatsapp_config": s.whatsapp_config, "key_id": s.key_id,
        "key_secret_masked": mask(s.key_secret), "webhook_secret_masked": mask(s.webhook_secret),
        "amount": s.amount, "hours": s.hours, "updated_at": s.updated_at,
        "webhook_url": env.FRONTEND_URL.rstrip("/") + "/api/v1/public/razorpay/webhook",
        "modes": {"whatsapp": bool(s.whatsapp_config), "link": bool(s.key_id and s.key_secret)},
        "test_keys": s.key_id.startswith("rzp_test_"),
    }


@router.get("/payment-settings")
async def read_payment_settings(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "view")):
    return _settings_view(await get_pay_settings(db))


@router.put("/payment-settings")
async def update_payment_settings(body: PaySettingsIn, db: AsyncSession = Depends(get_db),
                                  user: User = require_permission("settings", "edit")):
    from ...services.crm.engine import record_audit
    if body.key_id and not body.key_id.strip().startswith("rzp_"):
        raise HTTPException(status_code=400, detail="The Razorpay key id starts with rzp_test_ or rzp_live_")
    if body.amount is not None and not (1 <= body.amount <= 100000):
        raise HTTPException(status_code=400, detail="Amount must be between ₹1 and ₹1,00,000")
    if body.hours is not None and not (1 <= body.hours <= 720):
        raise HTTPException(status_code=400, detail="Valid for must be 1 to 720 hours")
    await save_pay_settings(db, body.model_dump(), user.id)
    record_audit(db, user.id, "update", "payment_settings", None,
                 after={k: v for k, v in body.model_dump().items() if k not in ("key_secret", "webhook_secret")})
    await db.commit()
    return _settings_view(await get_pay_settings(db))


@router.post("/payment-settings/test")
async def test_payment_settings(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "edit")):
    """Check the Razorpay keys with a harmless read."""
    await pay.load(db)
    if not pay.configured():
        raise HTTPException(status_code=400, detail="Enter the Razorpay key id and key secret first")
    try:
        await pay._rzp("GET", "payment_links?count=1")
    except pay.PaymentLinkError as e:
        raise HTTPException(status_code=400, detail=f"Razorpay refused the keys: {e}")
    return {"ok": True, "detail": "Razorpay accepted the keys"}


# ── reports: who sent links, who paid ──────────────────────────────
async def _team_ids(db: AsyncSession, tl_id: int) -> set[int]:
    """A team leader and their telecallers: reporting to them, or working one
    of their stores (own store or "also covers")."""
    stores = set((await db.execute(select(Store.id).where(Store.team_leader_id == tl_id))).scalars().all())
    covers = select(UserStoreAccess.user_id).where(UserStoreAccess.store_id.in_(stores or {-1}))
    ids = set((await db.execute(select(User.id).where(or_(
        User.team_leader_id == tl_id, User.store_id.in_(stores or {-1}), User.id.in_(covers))))).scalars().all())
    return ids | {tl_id}


async def _senders_in_scope(db: AsyncSession, scope: CrmScope, tl_id: int | None) -> set[int] | None:
    """Whose links the person may see (None = everyone)."""
    if scope.is_admin or scope.global_view:
        return await _team_ids(db, tl_id) if tl_id else None
    if scope.is_tl:
        return await _team_ids(db, scope.user.id)
    return {scope.user.id}


def _period(start: str, end: str) -> tuple[date, date]:
    today = ist_today()
    try:
        d_start = date.fromisoformat(start) if start else today.replace(day=1)
        d_end = date.fromisoformat(end) if end else today
    except ValueError:
        raise HTTPException(status_code=400, detail="start and end must be YYYY-MM-DD")
    if d_end < d_start:
        raise HTTPException(status_code=400, detail="The end date is before the start")
    return d_start, d_end


async def _links(db: AsyncSession, scope: CrmScope, start: str, end: str, tl_id: int | None,
                 user_id: int | None = None, status: str = "") -> tuple[list[PaymentLink], date, date]:
    d_start, d_end = _period(start, end)
    s_utc, e_utc = period_bounds(d_start, d_end)
    q = select(PaymentLink).where(PaymentLink.created_at >= s_utc, PaymentLink.created_at < e_utc,
                                  PaymentLink.status != "failed")
    senders = await _senders_in_scope(db, scope, tl_id)
    if senders is not None:
        q = q.where(PaymentLink.sent_by.in_(senders or {-1}))
    if user_id:
        q = q.where(PaymentLink.sent_by == user_id)
    if status == "waiting":
        q = q.where(PaymentLink.status == "sent")
    elif status:
        q = q.where(PaymentLink.status == status)
    return (await db.execute(q.order_by(PaymentLink.id.desc()))).scalars().all(), d_start, d_end


def _count(rows) -> dict:
    c = {"sent": len(rows), "paid": sum(r.status == "paid" for r in rows),
         "waiting": sum(r.status == "sent" for r in rows),
         "expired": sum(r.status in ("expired", "cancelled") for r in rows)}
    c["paid_pct"] = round(c["paid"] / c["sent"] * 100) if c["sent"] else None
    return c


@router.get("/payment-links/summary")
async def payment_links_summary(start: str = "", end: str = "", tl_id: Optional[int] = None,
                                db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Links sent in the period and how many were paid: per team leader and
    per telecaller. A telecaller sees themselves, a team leader their team,
    an admin everyone (tl_id narrows to one team)."""
    scope = await require_scope(db, user)
    await pay.load(db)
    links, d_start, d_end = await _links(db, scope, start, end, tl_id)
    senders = {l.sent_by for l in links} - {None}
    people = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(senders or {-1})))).scalars().all()}
    tl_role = (await db.execute(select(Role.id).where(Role.name == "Team Leader"))).scalar()
    store_tl = dict((await db.execute(select(Store.id, Store.team_leader_id).where(
        Store.id.in_({u.store_id for u in people.values() if u.store_id} or {-1})))).all())

    def tl_of(u: User | None) -> int | None:
        if u is None:
            return None
        if u.role_id == tl_role:
            return u.id
        return u.team_leader_id or store_tl.get(u.store_id)

    by_person: dict = {}
    for l in links:
        by_person.setdefault(l.sent_by, []).append(l)
    stores = dict((await db.execute(select(Store.id, Store.name).where(
        Store.id.in_({u.store_id for u in people.values() if u.store_id} or {-1})))).all())
    tl_names = await user_names(db, {tl_of(u) for u in people.values()} - {None})
    telecallers = [{"user_id": uid, "name": people[uid].name if uid in people else "—",
                    "role": "Team leader" if uid in people and people[uid].role_id == tl_role else "Telecaller",
                    "store": stores.get(people[uid].store_id) if uid in people else None,
                    "tl_id": tl_of(people.get(uid)), "team_leader": tl_names.get(tl_of(people.get(uid))),
                    **_count(rows)} for uid, rows in by_person.items()]
    telecallers.sort(key=lambda r: (-r["paid"], -r["sent"], r["name"].lower()))
    by_tl: dict = {}
    for r in telecallers:
        by_tl.setdefault(r["tl_id"], []).extend(by_person[r["user_id"]])
    team_leaders = [{"tl_id": tid, "name": tl_names.get(tid, "No team leader"), **_count(rows)}
                    for tid, rows in by_tl.items()]
    team_leaders.sort(key=lambda r: (-r["paid"], -r["sent"], r["name"].lower()))
    return {"start": d_start.isoformat(), "end": d_end.isoformat(), "enabled": pay.enabled(),
            "level": "admin" if (scope.is_admin or scope.global_view) else "team" if scope.is_tl else "own",
            "total": _count(links), "team_leaders": team_leaders, "telecallers": telecallers}


@router.get("/payment-links")
async def payment_links_list(start: str = "", end: str = "", tl_id: Optional[int] = None,
                             user_id: Optional[int] = None, status: str = "paid",
                             db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """The customers behind the numbers (paid by default)."""
    if status not in ("", "paid", "waiting", "expired", "cancelled"):
        raise HTTPException(status_code=400, detail="Unknown status")
    scope = await require_scope(db, user)
    links, _, _ = await _links(db, scope, start, end, tl_id, user_id, status)
    names, stores = await user_names(db, {l.sent_by for l in links}), await _store_names(db, links)
    return {"items": [pay.link_row(l, names, stores) for l in links[:500]], "total": len(links)}


# ── public: the customer's Pay button, and Razorpay ─────────────────
@public_router.get("/pay/{token}")
async def open_payment_link(token: str, db: AsyncSession = Depends(get_db)):
    """The WhatsApp Pay button: note the first open, go on to Razorpay."""
    pl = (await db.execute(select(PaymentLink).where(PaymentLink.token == token[:40]))).scalar_one_or_none()
    if pl is None or not pl.short_url:
        return HTMLResponse("<h3 style='font-family:sans-serif'>This payment link is not valid.</h3>", status_code=404)
    if pl.status == "paid":
        return HTMLResponse("<h3 style='font-family:sans-serif'>Thank you — this booking is already paid.</h3>")
    if pl.opened_at is None:
        pl.opened_at = utcnow()
        lead = await db.get(TeleCallLead, pl.lead_id)
        if lead:
            add_activity(db, lead, "payment", at=pl.opened_at, new_value="Link opened",
                         notes="Customer opened the payment link", meta={"payment_link": pl.id})
        await db.commit()
    return RedirectResponse(pl.short_url, status_code=302)


@public_router.post("/razorpay/webhook")
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    await pay.load(db)
    if not pay.verify_signature(body, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        event = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Not JSON")
    what, alerts = await pay.handle_webhook(db, event)
    await db.commit()
    await emit_alerts(alerts)
    if what == "paid" and alerts:
        entity = ((event.get("payload") or {}).get("payment_link") or {}).get("entity") or {}
        pl = (await db.execute(select(PaymentLink).where(PaymentLink.rzp_link_id == entity.get("id")))).scalar_one_or_none()
        if pl:
            await pay.after_paid(pl.lead_id)
    return {"ok": True, "result": what}
