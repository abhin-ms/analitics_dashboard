"""Public webhook for leads from outside systems (third-party website now;
WhatsApp and Facebook later). Not behind user login — protected by a shared
secret (WEBSITE_WEBHOOK_KEY in backend/.env), sent as the X-Api-Key header or
?key= query parameter, plus a per-IP rate limit.
"""
from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...db.session import get_db
from ...models.models import Store
from ...services.crm.intake import ingest_website_lead

router = APIRouter(prefix="/public", tags=["Public lead webhooks"])

_hits: dict[str, deque] = defaultdict(deque)
RATE_LIMIT = 60  # calls per minute per IP


def _check_key(request: Request) -> None:
    expected = settings.WEBSITE_WEBHOOK_KEY
    if not expected:
        raise HTTPException(status_code=503, detail="Website webhook is not configured on the server")
    given = request.headers.get("x-api-key") or request.query_params.get("key") or ""
    if not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _rate_limit(request: Request) -> str:
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "?")
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests")
    q.append(now)
    return ip


async def _payload(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    try:
        if "application/json" in ctype:
            data = await request.json()
        else:
            form = await request.form()
            data = {k: v for k, v in form.items()}
    except Exception:
        raise HTTPException(status_code=400, detail="Send the booking as JSON or form fields")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):  # common wrapper: {"data": {...}}
        data = {**data, **data["data"]}
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Expected one booking object")
    return data


@router.post("/website-leads")
async def website_lead(request: Request, db: AsyncSession = Depends(get_db)):
    """One paid website booking → one premium lead. Unpaid or incomplete
    entries are logged but not turned into leads."""
    ip = _rate_limit(request)
    _check_key(request)
    result = await ingest_website_lead(db, await _payload(request), remote_ip=ip)
    if result["status"] == "invalid":
        raise HTTPException(status_code=422, detail=result["detail"])
    return result


@router.get("/stores")
async def public_store_list(request: Request, db: AsyncSession = Depends(get_db)):
    """Active stores (id, name, state) so the website's "Preferred store"
    dropdown can send our store_id and every booking routes exactly."""
    _rate_limit(request)
    _check_key(request)
    rows = (await db.execute(select(Store.id, Store.name, Store.region, Store.country)
                             .where(Store.is_active == True).order_by(Store.country, Store.region, Store.name))).all()  # noqa: E712
    return {"stores": [{"id": r[0], "name": r[1], "state": r[2] or None, "country": r[3]} for r in rows]}
