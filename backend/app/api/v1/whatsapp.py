"""Settings → WhatsApp: Cloud API setup, the numbers alerts go to, and a
test sender for each template. Plus the public webhook Meta calls with the
delivery status (sent / delivered / read / failed) of every message.

Meta → app → WhatsApp → Configuration:
  Callback URL:  https://<server>/api/v1/public/whatsapp/webhook
  Verify token:  shown on the Setup tab (generated on first save)
  Subscribe to:  messages
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import require_permission
from ...db.session import get_db
from ...models.models import Role, Store, User, WhatsAppContact, WhatsAppMessage
from ...services.crm.engine import record_audit
from ...services.crm.timeutil import iso_utc
from ...services.whatsapp import templates as wa_templates
from ...services.whatsapp.client import (
    WhatsAppError, apply_statuses, check_phone_number, list_templates, meta_buttons, send_template, signature_ok,
    subscribe_app, subscribed_apps, summarize,
)
from ...services.whatsapp.config import (
    get_config, last_webhook_at, last_webhook_error, log_webhook, mark_webhook_received, mark_webhook_rejected,
    mask, normalize_phone, save_config, valid_phone, webhook_log, webhook_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
public_router = APIRouter(prefix="/public/whatsapp", tags=["Public lead webhooks"])


# ── Tab 1: setup ────────────────────────────────────────────────────

async def _config_view(db: AsyncSession) -> dict:
    cfg = await get_config(db)
    return {
        "configured": cfg.ready,
        "enabled": cfg.ready and cfg.enabled,
        "phone_number_id": cfg.phone_number_id,
        "waba_id": cfg.waba_id,
        "graph_version": cfg.version,
        "access_token_masked": mask(cfg.access_token),
        "app_secret_masked": mask(cfg.app_secret),
        "app_secret_from_env": not cfg.app_secret and bool(cfg.signing_secret),
        "display_phone": cfg.display_phone,
        "verified_name": cfg.verified_name,
        "updated_at": cfg.updated_at,
        "webhook_url": webhook_url(),
        "verify_token": cfg.verify_token if cfg.ready else "",
        "last_webhook_at": await last_webhook_at(db),
        "last_webhook_error": await last_webhook_error(db),
    }


@router.get("/config")
async def read_config(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "view")):
    return await _config_view(db)


class ConfigIn(BaseModel):
    access_token: Optional[str] = None   # blank = keep the saved one
    phone_number_id: str = Field(min_length=5, max_length=40)
    waba_id: Optional[str] = None
    app_secret: Optional[str] = None     # blank = keep the saved one
    graph_version: Optional[str] = None


@router.put("/config")
async def update_config(body: ConfigIn, db: AsyncSession = Depends(get_db),
                        user: User = require_permission("settings", "edit")):
    cfg = await get_config(db)
    first_setup = not cfg.ready
    if body.access_token and body.access_token.strip():
        cfg.access_token = body.access_token.strip()
    if not cfg.access_token:
        raise HTTPException(status_code=400, detail="Enter the access token")
    cfg.phone_number_id = body.phone_number_id.strip()
    cfg.waba_id = (body.waba_id or "").strip()
    if body.app_secret and body.app_secret.strip():
        cfg.app_secret = body.app_secret.strip()
    if body.graph_version is not None:
        cfg.graph_version = body.graph_version.strip()
    try:
        info = await check_phone_number(cfg)
    except WhatsAppError as e:
        raise HTTPException(status_code=400, detail=f"Meta did not accept these details: {e}")
    cfg.display_phone = info.get("display_phone_number", "")
    cfg.verified_name = info.get("verified_name", "")
    if first_setup:
        cfg.enabled = True
    await save_config(db, cfg, user.id)
    record_audit(db, user.id, "update", "whatsapp_config", None,
                 after={"phone_number_id": cfg.phone_number_id, "waba_id": cfg.waba_id})
    await db.commit()
    return await _config_view(db)


class EnabledIn(BaseModel):
    enabled: bool


@router.put("/config/enabled")
async def set_enabled(body: EnabledIn, db: AsyncSession = Depends(get_db),
                      user: User = require_permission("settings", "edit")):
    cfg = await get_config(db)
    if body.enabled and not cfg.ready:
        raise HTTPException(status_code=400, detail="Save the WhatsApp details first")
    cfg.enabled = body.enabled
    await save_config(db, cfg, user.id)
    record_audit(db, user.id, "enable" if body.enabled else "disable", "whatsapp_config", None,
                 after={"enabled": body.enabled})
    await db.commit()
    return await _config_view(db)


@router.get("/webhook-check")
async def webhook_check(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "view")):
    """Is this WhatsApp Business Account subscribed to an app? If not, Meta
    sends no delivery statuses even when the callback URL verified fine."""
    cfg = await get_config(db)
    if not cfg.ready or not cfg.waba_id:
        return {"checked": False, "reason": "Add the WhatsApp Business Account ID on the Setup tab to check this."}
    try:
        apps = await subscribed_apps(cfg)
    except WhatsAppError as e:
        return {"checked": False, "reason": f"Meta: {e}"}
    return {"checked": True, "subscribed": bool(apps), "apps": [a.get("name") or a.get("id") for a in apps]}


@router.post("/webhook-subscribe")
async def webhook_subscribe(db: AsyncSession = Depends(get_db), user: User = require_permission("settings", "edit")):
    cfg = await get_config(db)
    if not cfg.ready or not cfg.waba_id:
        raise HTTPException(status_code=400, detail="Add the WhatsApp Business Account ID on the Setup tab first")
    try:
        await subscribe_app(cfg)
        apps = await subscribed_apps(cfg)
    except WhatsAppError as e:
        raise HTTPException(status_code=400, detail=f"Meta refused: {e}")
    record_audit(db, user.id, "subscribe", "whatsapp_webhook", None, after={"waba_id": cfg.waba_id})
    await db.commit()
    return {"checked": True, "subscribed": bool(apps), "apps": [a.get("name") or a.get("id") for a in apps]}


@router.get("/webhook-log")
async def read_webhook_log(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "view")):
    return {"items": await webhook_log(db), "last_webhook_at": await last_webhook_at(db)}


SELFTEST_HEADER = "x-bp-selftest"


@router.post("/webhook-selftest")
async def webhook_selftest(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "edit")):
    """Send a signed sample update to our own public webhook URL, the way
    Meta would. Shows whether the URL, nginx and the App secret all work;
    if this arrives but Meta's calls don't, the problem is on Meta's side."""
    cfg = await get_config(db)
    if not cfg.signing_secrets:
        raise HTTPException(status_code=400, detail="Enter the App secret on the Setup tab first")
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "selftest", "changes": [{
        "field": "messages", "value": {"statuses": [
            {"id": "bp-selftest", "status": "delivered", "timestamp": str(int(time.time()))}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(cfg.signing_secrets[0].encode(), raw, hashlib.sha256).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(webhook_url(), content=raw, headers={
                "content-type": "application/json", "x-hub-signature-256": sig, SELFTEST_HEADER: "1"})
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"Could not reach {webhook_url()}: {e}"}
    if resp.status_code != 200:
        return {"ok": False, "detail": f"The webhook answered HTTP {resp.status_code}: {resp.text[:200]}"}
    return {"ok": True, "detail": "The test call reached the webhook and was accepted."}


@router.post("/config/new-verify-token")
async def new_verify_token(db: AsyncSession = Depends(get_db), user: User = require_permission("settings", "edit")):
    cfg = await get_config(db)
    if not cfg.ready:
        raise HTTPException(status_code=400, detail="Save the WhatsApp details first")
    cfg.verify_token = ""
    await save_config(db, cfg, user.id)
    await db.commit()
    return await _config_view(db)


# ── Tab 2: numbers ──────────────────────────────────────────────────

async def _users_with_role(db: AsyncSession, role: str) -> list[User]:
    return list((await db.execute(
        select(User).join(Role, Role.id == User.role_id)
        .where(Role.name == role, User.is_active == True)  # noqa: E712
        .order_by(User.name)
    )).scalars().all())


@router.get("/contacts")
async def read_contacts(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "view")):
    rows = (await db.execute(select(WhatsAppContact).order_by(WhatsAppContact.id))).scalars().all()
    by_role: dict[str, list[WhatsAppContact]] = {}
    for r in rows:
        by_role.setdefault(r.role, []).append(r)

    def user_phone(role: str, uid: int) -> str:
        return next((r.phone for r in by_role.get(role, []) if r.user_id == uid), "")

    ceo_users = await _users_with_role(db, "CEO")
    ceo_ids = {u.id for u in ceo_users}
    stores = (await db.execute(select(Store.id, Store.name).order_by(Store.name))).all()
    return {
        "ceo": [{"user_id": u.id, "name": u.name, "phone": user_phone("ceo", u.id)} for u in ceo_users],
        # CEO numbers typed in without a user account behind them
        "ceo_extra": [{"name": r.name or "", "phone": r.phone} for r in by_role.get("ceo", [])
                      if r.user_id is None or r.user_id not in ceo_ids],
        "team_leaders": [{"user_id": u.id, "name": u.name, "phone": user_phone("team_leader", u.id)}
                         for u in await _users_with_role(db, "Team Leader")],
        "telecallers": [{
            "user_id": u.id, "name": u.name,
            "rows": [{"store_id": r.store_id, "phone": r.phone}
                     for r in by_role.get("telecaller", []) if r.user_id == u.id],
        } for u in await _users_with_role(db, "Telecaller")],
        "stores": [{"store_id": sid, "name": name,
                    "phone": next((r.phone for r in by_role.get("store", []) if r.store_id == sid), "")}
                   for sid, name in stores],
    }


class UserPhone(BaseModel):
    user_id: int
    phone: str = ""


class NamedPhone(BaseModel):
    name: str = ""
    phone: str = ""


class TelecallerPhone(BaseModel):
    user_id: int
    store_id: Optional[int] = None
    phone: str = ""


class StorePhone(BaseModel):
    store_id: int
    phone: str = ""


class ContactsIn(BaseModel):
    ceo: list[UserPhone] = []
    ceo_extra: list[NamedPhone] = []
    team_leaders: list[UserPhone] = []
    telecallers: list[TelecallerPhone] = []
    stores: list[StorePhone] = []


@router.put("/contacts")
async def save_contacts(body: ContactsIn, db: AsyncSession = Depends(get_db),
                        user: User = require_permission("settings", "edit")):
    """Replaces every saved number with the ones sent; blank numbers are dropped."""
    new: list[WhatsAppContact] = []
    bad: list[str] = []

    def add(role: str, raw: str, label: str, **kw):
        if not raw.strip():
            return
        phone = normalize_phone(raw)
        if not valid_phone(phone):
            bad.append(f"{label} ({raw})")
            return
        new.append(WhatsAppContact(role=role, phone=phone, updated_by=user.id, **kw))

    names = dict((await db.execute(select(User.id, User.name))).all())
    store_names = dict((await db.execute(select(Store.id, Store.name))).all())
    for r in body.ceo:
        add("ceo", r.phone, names.get(r.user_id, "CEO"), user_id=r.user_id)
    for r in body.ceo_extra:
        if r.phone.strip() and not r.name.strip():
            raise HTTPException(status_code=400, detail="Give each extra CEO number a name")
        add("ceo", r.phone, r.name or "CEO", name=r.name.strip()[:100])
    for r in body.team_leaders:
        add("team_leader", r.phone, names.get(r.user_id, "Team leader"), user_id=r.user_id)
    for r in body.telecallers:
        if r.phone.strip() and r.store_id is not None and r.store_id not in store_names:
            raise HTTPException(status_code=400, detail="Unknown store")
        add("telecaller", r.phone, names.get(r.user_id, "Telecaller"), user_id=r.user_id, store_id=r.store_id)
    for r in body.stores:
        add("store", r.phone, store_names.get(r.store_id, "Store"), store_id=r.store_id)
    if bad:
        raise HTTPException(status_code=400, detail=f"Check these numbers: {', '.join(bad)}")

    await db.execute(delete(WhatsAppContact))
    db.add_all(new)
    record_audit(db, user.id, "update", "whatsapp_contacts", None, after={"count": len(new)})
    await db.commit()
    return {"ok": True, "saved": len(new)}


# ── Tab 3: test templates ───────────────────────────────────────────

@router.get("/templates")
async def read_templates(db: AsyncSession = Depends(get_db), _u: User = require_permission("settings", "view")):
    cfg = await get_config(db)
    meta_status: dict[str, list[dict]] = {}
    meta_error = None
    if cfg.ready and cfg.waba_id:
        try:
            for t in await list_templates(cfg):
                meta_status.setdefault(t.get("name"), []).append(
                    {"status": t.get("status"), "language": t.get("language"), "category": t.get("category"),
                     "buttons": meta_buttons(t)})
        except WhatsAppError as e:
            meta_error = str(e)
    return {
        "templates": [{**wa_templates.public_view(t), "meta": meta_status.get(t["name"], [])}
                      for t in wa_templates.TEMPLATES],
        "meta_checked": bool(cfg.ready and cfg.waba_id and not meta_error),
        "meta_error": meta_error,
    }


class TestSendIn(BaseModel):
    template: str
    to: str
    language: str = "en"
    values: dict[str, str] = {}
    button_values: dict[int, str] = {}
    include_buttons: list[int] = []


def _message_row(m: WhatsAppMessage, names: dict[int, str] | None = None) -> dict:
    return {
        "id": m.id, "wa_message_id": m.wa_message_id, "to": m.to_phone, "template": m.template,
        "language": m.language, "purpose": m.purpose, "status": m.status,
        "error_code": m.error_code, "error": m.error_text,
        "created_at": iso_utc(m.created_at), "sent_at": iso_utc(m.sent_at), "delivered_at": iso_utc(m.delivered_at),
        "read_at": iso_utc(m.read_at), "failed_at": iso_utc(m.failed_at),
        "sent_by": (names or {}).get(m.sent_by) if m.sent_by else None,
    }


@router.post("/test-send")
async def test_send(body: TestSendIn, db: AsyncSession = Depends(get_db),
                    user: User = require_permission("settings", "edit")):
    cfg = await get_config(db)
    if not cfg.ready:
        raise HTTPException(status_code=400, detail="Finish the Setup tab first")
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="WhatsApp is turned off. Turn it on in the Setup tab to send messages.")
    t = wa_templates.BY_NAME.get(body.template)
    if not t:
        raise HTTPException(status_code=400, detail="Unknown template")
    to = normalize_phone(body.to)
    if not valid_phone(to):
        raise HTTPException(status_code=400, detail="Enter the number with country code, e.g. 919876543210")
    try:
        components = wa_templates.build_components(t, body.values, body.button_values, set(body.include_buttons))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        msg = await send_template(db, cfg, to=to, template=t["name"], language=body.language.strip() or "en",
                                  components=components, params={"values": body.values, "buttons": body.button_values},
                                  purpose="test", sent_by=user.id)
    except WhatsAppError as e:
        raise HTTPException(status_code=400, detail=f"Meta refused the message: {e}")
    return {"ok": True, "message": _message_row(msg, {user.id: user.name})}


@router.get("/messages")
async def read_messages(limit: int = Query(30, ge=1, le=200), db: AsyncSession = Depends(get_db),
                        _u: User = require_permission("settings", "view")):
    rows = (await db.execute(
        select(WhatsAppMessage).order_by(WhatsAppMessage.id.desc()).limit(limit)
    )).scalars().all()
    names = dict((await db.execute(
        select(User.id, User.name).where(User.id.in_({r.sent_by for r in rows if r.sent_by} or {-1}))
    )).all())
    return {"items": [_message_row(r, names) for r in rows]}


# ── Public webhook (Meta) ───────────────────────────────────────────

def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@public_router.get("/webhook")
async def verify(request: Request, db: AsyncSession = Depends(get_db)):
    """Meta's one-time check when the callback URL is saved."""
    q = request.query_params
    expected = (await get_config(db)).verify_token
    if expected and q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token") or "", expected):
        await log_webhook(db, kind="verify", ok=True, status=200, summary="Verify check: passed", ip=_ip(request))
        await db.commit()
        return Response(content=q.get("hub.challenge") or "", media_type="text/plain")
    reason = ("Verify check failed: the verify token doesn't match the one on the Setup tab"
              if q.get("hub.verify_token") else "Verify check failed: no verify token sent (opened in a browser?)")
    await log_webhook(db, kind="verify", ok=False, status=403, summary=reason, ip=_ip(request))
    await db.commit()
    return Response(content="Verification failed", status_code=403)


@public_router.post("/webhook")
async def receive(request: Request, db: AsyncSession = Depends(get_db)):
    cfg = await get_config(db)
    test = request.headers.get(SELFTEST_HEADER) == "1"

    async def reject(status: int, reason: str):
        logger.warning("WhatsApp webhook refused: %s", reason)
        await mark_webhook_rejected(db, reason)
        await log_webhook(db, kind="update", ok=False, status=status, summary=f"Refused: {reason}",
                          ip=_ip(request), test=test)
        await db.commit()
        raise HTTPException(status_code=status, detail=reason)

    if not cfg.signing_secrets:
        await reject(503, "No App secret saved, so the app can't check that the call came from Meta. "
                          "Enter the App secret on the Setup tab.")
    body = await request.body()
    if not signature_ok(cfg.signing_secrets, body, request.headers.get("x-hub-signature-256", "")):
        await reject(403, "Meta's signature didn't match the App secret. Enter the App secret of the Meta app "
                          "that owns this WhatsApp number (App settings → Basic).")
    try:
        data = json.loads(body)
    except ValueError:
        await reject(400, "The call's body was not JSON")
    if data.get("object") != "whatsapp_business_account":
        await log_webhook(db, kind="update", ok=True, status=200, ip=_ip(request), test=test,
                          summary=f"Ignored: not a WhatsApp call (object: {data.get('object')})")
        await db.commit()
        return {"ok": True, "ignored": True}
    updated = await apply_statuses(db, data)
    await log_webhook(db, kind="update", ok=True, status=200, summary=summarize(data, updated),
                      ip=_ip(request), test=test)
    if not test:
        await mark_webhook_received(db)
    await db.commit()
    # Customer replies and button taps arrive here too; stage 2 acts on them.
    return {"ok": True, "updated": updated}
