"""WhatsApp Cloud API settings, stored as JSON in the key/value `settings`
table. The access token and app secret are kept encrypted (same Fernet key
as the Instagram tokens) and never sent back to the browser."""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...instagram.utils import decrypt_token, encrypt_token
from ...models.models import Setting

CONFIG_KEY = "whatsapp.config"
LAST_WEBHOOK_KEY = "whatsapp.last_webhook_at"
WEBHOOK_PATH = "/api/v1/public/whatsapp/webhook"


@dataclass
class WhatsAppConfig:
    phone_number_id: str = ""
    waba_id: str = ""
    graph_version: str = ""
    access_token: str = ""
    app_secret: str = ""
    verify_token: str = ""
    display_phone: str = ""
    verified_name: str = ""
    # The on/off switch on the Setup tab. Off = nothing is sent (tests
    # included); saved details stay and delivery updates still arrive.
    enabled: bool = True
    updated_at: str | None = None

    @property
    def version(self) -> str:
        return self.graph_version or settings.META_GRAPH_VERSION or "v26.0"

    @property
    def ready(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    @property
    def active(self) -> bool:
        return self.ready and self.enabled

    @property
    def signing_secret(self) -> str:
        # The WhatsApp app may be the same Meta app as the lead forms.
        return self.app_secret or settings.META_APP_SECRET


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return decrypt_token(value)
    except Exception:  # key changed: treat as not set rather than crash
        return ""


async def _raw(db: AsyncSession, key: str) -> str:
    row = await db.get(Setting, key)
    return row.value if row and row.value else ""


async def get_config(db: AsyncSession) -> WhatsAppConfig:
    try:
        data = json.loads(await _raw(db, CONFIG_KEY) or "{}")
    except ValueError:
        data = {}
    return WhatsAppConfig(
        phone_number_id=data.get("phone_number_id", ""),
        waba_id=data.get("waba_id", ""),
        graph_version=data.get("graph_version", ""),
        access_token=_decrypt(data.get("access_token_enc", "")),
        app_secret=_decrypt(data.get("app_secret_enc", "")),
        verify_token=data.get("verify_token", ""),
        display_phone=data.get("display_phone", ""),
        verified_name=data.get("verified_name", ""),
        enabled=bool(data.get("enabled", True)),
        updated_at=data.get("updated_at"),
    )


async def save_config(db: AsyncSession, cfg: WhatsAppConfig, user_id: int | None) -> None:
    if not cfg.verify_token:
        cfg.verify_token = secrets.token_urlsafe(24)
    cfg.updated_at = datetime.utcnow().isoformat()
    value = json.dumps({
        "phone_number_id": cfg.phone_number_id,
        "waba_id": cfg.waba_id,
        "graph_version": cfg.graph_version,
        "access_token_enc": encrypt_token(cfg.access_token) if cfg.access_token else "",
        "app_secret_enc": encrypt_token(cfg.app_secret) if cfg.app_secret else "",
        "verify_token": cfg.verify_token,
        "display_phone": cfg.display_phone,
        "verified_name": cfg.verified_name,
        "enabled": cfg.enabled,
        "updated_at": cfg.updated_at,
    })
    row = await db.get(Setting, CONFIG_KEY)
    if row:
        row.value = value
        row.updated_by = user_id
    else:
        db.add(Setting(key=CONFIG_KEY, value=value, updated_by=user_id))


async def mark_webhook_received(db: AsyncSession) -> None:
    now = datetime.utcnow().isoformat()
    row = await db.get(Setting, LAST_WEBHOOK_KEY)
    if row:
        row.value = now
    else:
        db.add(Setting(key=LAST_WEBHOOK_KEY, value=now))


async def last_webhook_at(db: AsyncSession) -> str | None:
    return await _raw(db, LAST_WEBHOOK_KEY) or None


def webhook_url() -> str:
    return settings.FRONTEND_URL.rstrip("/") + WEBHOOK_PATH


def mask(secret: str) -> str:
    if not secret:
        return ""
    return f"{'•' * 8}{secret[-4:]}" if len(secret) > 8 else "•" * len(secret)


def normalize_phone(raw: str) -> str:
    """Digits with country code, the form the Cloud API wants: a 10-digit
    Indian mobile gets 91, a leading 0 or + is dropped."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def valid_phone(digits: str) -> bool:
    return 10 < len(digits) <= 15
