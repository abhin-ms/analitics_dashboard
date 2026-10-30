"""Payment settings, entered by an admin in Settings → WhatsApp → Payments
and kept in the database (secrets encrypted, like the WhatsApp token): the
WhatsApp payment configuration name ("Review and Pay"), the Razorpay key id,
key secret and webhook secret, the amount and how long a request is valid.
A field left empty there falls back to the server's environment
(WHATSAPP_PAY_CONFIG, RAZORPAY_*, PAYMENT_LINK_*), so nothing set up on the
server before stops working."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...instagram.utils import decrypt_token, encrypt_token
from ...models.models import Setting

KEY = "payments.config"


@dataclass
class PaySettings:
    whatsapp_config: str = ""
    key_id: str = ""
    key_secret: str = ""
    webhook_secret: str = ""
    amount: int = 99
    hours: int = 24
    # the business on the order (Meta asks for an importer and its address on
    # every item of an order that has no product catalog)
    business_name: str = "Break Protection"
    address_line1: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    updated_at: str | None = None

    def address_ready(self) -> bool:
        return bool(self.business_name and self.address_line1 and self.city and self.postal_code)


def _env() -> PaySettings:
    return PaySettings(whatsapp_config=settings.WHATSAPP_PAY_CONFIG, key_id=settings.RAZORPAY_KEY_ID,
                       key_secret=settings.RAZORPAY_KEY_SECRET, webhook_secret=settings.RAZORPAY_WEBHOOK_SECRET,
                       amount=int(settings.PAYMENT_LINK_AMOUNT), hours=int(settings.PAYMENT_LINK_HOURS))


def _dec(value: str) -> str:
    if not value:
        return ""
    try:
        return decrypt_token(value)
    except Exception:  # key changed: treat as not set rather than crash
        return ""


async def _stored(db: AsyncSession) -> dict:
    row = await db.get(Setting, KEY)
    try:
        return json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


async def get_pay_settings(db: AsyncSession) -> PaySettings:
    """What the dashboard saved, each empty field filled from the server's environment."""
    d, env = await _stored(db), _env()
    return PaySettings(
        whatsapp_config=d.get("whatsapp_config") or env.whatsapp_config,
        key_id=d.get("key_id") or env.key_id,
        key_secret=_dec(d.get("key_secret_enc", "")) or env.key_secret,
        webhook_secret=_dec(d.get("webhook_secret_enc", "")) or env.webhook_secret,
        amount=int(d.get("amount") or env.amount),
        hours=int(d.get("hours") or env.hours),
        business_name=d.get("business_name") or "Break Protection",
        address_line1=d.get("address_line1", ""), city=d.get("city", ""), state=d.get("state", ""),
        postal_code=d.get("postal_code", ""),
        updated_at=d.get("updated_at"),
    )


async def save_pay_settings(db: AsyncSession, data: dict, user_id: int | None) -> None:
    """Save from the form. A secret left blank keeps the saved one; send
    clear_<name>=True to remove it."""
    d = await _stored(db)
    for k in ("whatsapp_config", "key_id", "business_name", "address_line1", "city", "state", "postal_code"):
        if data.get(k) is not None:
            d[k] = str(data[k]).strip()
    for k in ("key_secret", "webhook_secret"):
        if data.get(f"clear_{k}"):
            d[f"{k}_enc"] = ""
        elif (data.get(k) or "").strip():
            d[f"{k}_enc"] = encrypt_token(data[k].strip())
    for k in ("amount", "hours"):
        if data.get(k):
            d[k] = int(data[k])
    d["updated_at"], d["updated_by"] = datetime.utcnow().isoformat(), user_id
    row = await db.get(Setting, KEY)
    if row:
        row.value = json.dumps(d)
    else:
        db.add(Setting(key=KEY, value=json.dumps(d)))


def mask(secret: str) -> str:
    if not secret:
        return ""
    return f"{'•' * 8}{secret[-4:]}" if len(secret) > 8 else "•" * len(secret)
