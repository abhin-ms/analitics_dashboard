"""Meta WhatsApp Cloud API calls and delivery-status bookkeeping."""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import WhatsAppMessage
from .config import WhatsAppConfig

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com"
# Statuses only move forward: a late "delivered" never undoes a "read".
RANK = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3}


class WhatsAppError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def _error(resp: httpx.Response) -> WhatsAppError:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    detail = (err.get("error_data") or {}).get("details") or err.get("error_user_msg") or err.get("message")
    return WhatsAppError(detail or f"Meta returned HTTP {resp.status_code}", str(err.get("code") or resp.status_code))


async def _call(cfg: WhatsAppConfig, method: str, path: str, **kw) -> dict:
    url = f"{GRAPH}/{cfg.version}/{path}"
    headers = {"Authorization": f"Bearer {cfg.access_token}"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(method, url, headers=headers, **kw)
    except httpx.HTTPError as e:
        raise WhatsAppError(f"Could not reach Meta: {e}") from e
    if resp.status_code >= 400:
        raise _error(resp)
    return resp.json()


async def check_phone_number(cfg: WhatsAppConfig) -> dict:
    """Confirms the token can use this phone number id; returns its details."""
    return await _call(cfg, "GET", cfg.phone_number_id,
                       params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"})


async def list_templates(cfg: WhatsAppConfig) -> list[dict]:
    """Templates on the WhatsApp Business Account with their approval status."""
    data = await _call(cfg, "GET", f"{cfg.waba_id}/message_templates",
                       params={"fields": "name,status,language,category", "limit": 200})
    return data.get("data", [])


async def send_template(db: AsyncSession, cfg: WhatsAppConfig, *, to: str, template: str, language: str,
                        components: list[dict], params: dict, purpose: str, sent_by: int | None,
                        lead_id: int | None = None) -> WhatsAppMessage:
    """Send a template and log it. A Meta refusal is logged as failed too,
    then raised so the caller can show it."""
    msg = WhatsAppMessage(to_phone=to, template=template, language=language, purpose=purpose,
                          params=params, sent_by=sent_by, lead_id=lead_id, status="accepted",
                          created_at=datetime.utcnow())
    db.add(msg)
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
            "template": {"name": template, "language": {"code": language}, "components": components}}
    try:
        data = await _call(cfg, "POST", f"{cfg.phone_number_id}/messages", json=body)
    except WhatsAppError as e:
        msg.status, msg.error_code, msg.error_text, msg.failed_at = "failed", e.code, str(e), datetime.utcnow()
        await db.commit()
        raise
    msg.wa_message_id = ((data.get("messages") or [{}])[0]).get("id")
    await db.commit()
    return msg


def signature_ok(secret: str, body: bytes, header: str) -> bool:
    if not secret or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], digest)


def _ts(value) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return datetime.utcnow()


async def apply_statuses(db: AsyncSession, payload: dict) -> int:
    """Record the sent / delivered / read / failed updates in a webhook call."""
    updated = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for st in (change.get("value") or {}).get("statuses", []) or []:
                msg = (await db.execute(
                    select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == st.get("id"))
                )).scalar_one_or_none()
                if not msg:
                    continue
                status, at = st.get("status"), _ts(st.get("timestamp"))
                if status == "failed":
                    err = (st.get("errors") or [{}])[0]
                    msg.status, msg.failed_at = "failed", at
                    msg.error_code = str(err.get("code") or "")
                    msg.error_text = (err.get("error_data") or {}).get("details") or err.get("message") or err.get("title")
                elif status in ("sent", "delivered", "read"):
                    setattr(msg, f"{status}_at", getattr(msg, f"{status}_at") or at)
                    if msg.status != "failed" and RANK[status] > RANK.get(msg.status, 0):
                        msg.status = status
                else:
                    continue
                updated += 1
    return updated
