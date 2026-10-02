"""Meta Lead Ads webhook (Facebook / Instagram lead forms).

Set in developers.facebook.com → app → Webhooks → Page → leadgen:
  Callback URL:  https://<server>/api/v1/public/meta/leads-webhook
  Verify token:  META_VERIFY_TOKEN from backend/.env
Calls are signed by Meta with the app secret (X-Hub-Signature-256); unsigned
or wrongly signed calls are refused.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...db.session import get_db
from ...services.crm.meta_leads import ingest_meta_lead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/meta", tags=["Public lead webhooks"])


@router.get("/leads-webhook")
async def verify(request: Request):
    """Meta's one-time check when the callback URL is saved."""
    q = request.query_params
    expected = settings.META_VERIFY_TOKEN
    if expected and q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token") or "", expected):
        return Response(content=q.get("hub.challenge") or "", media_type="text/plain")
    return Response(content="Verification failed", status_code=403)


def _signed(body: bytes, header: str) -> bool:
    secret = settings.META_APP_SECRET
    if not secret or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], digest)


@router.post("/leads-webhook")
async def receive(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.META_APP_SECRET:
        raise HTTPException(status_code=503, detail="Meta webhook is not configured on the server")
    body = await request.body()
    if not _signed(body, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(status_code=403, detail="Invalid signature")
    try:
        data = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if data.get("object") != "page":
        return {"ok": True, "ignored": True}

    results = []
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = {**(change.get("value") or {})}
            value.setdefault("page_id", entry.get("id"))
            try:
                results.append(await ingest_meta_lead(db, value))
            except Exception:  # keep the other leads in this call; the lead stays retryable
                logger.exception("Meta lead %s failed", value.get("leadgen_id"))
                await db.rollback()
                results.append({"ok": False, "status": "error", "leadgen_id": value.get("leadgen_id")})
    # Errors are recorded in meta_leads and can be re-read from CRM Settings;
    # answering 200 stops Meta from retrying the whole batch for hours.
    return {"ok": True, "results": results}
