"""The signed-in user's "new lead" notifications (header bell)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user
from ...db.session import get_db
from ...models.models import CrmNotification
from ...services.crm.notify import notification_dict
from ...services.crm.timeutil import utcnow

router = APIRouter(prefix="/crm/notifications", tags=["Telecalling CRM"])


@router.get("")
async def list_notifications(limit: int = Query(30, ge=1, le=100), db: AsyncSession = Depends(get_db),
                             user=Depends(get_current_user)):
    rows = (await db.execute(
        select(CrmNotification).where(CrmNotification.user_id == user.id)
        .order_by(CrmNotification.created_at.desc(), CrmNotification.id.desc()).limit(limit)
    )).scalars().all()
    unread = (await db.execute(select(func.count(CrmNotification.id)).where(
        CrmNotification.user_id == user.id, CrmNotification.read_at.is_(None)))).scalar() or 0
    return {"items": [notification_dict(n) for n in rows], "unread": int(unread)}


class MarkRead(BaseModel):
    ids: Optional[list[int]] = None  # none = all


@router.post("/read")
async def mark_read(body: MarkRead, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    q = update(CrmNotification).where(CrmNotification.user_id == user.id, CrmNotification.read_at.is_(None))
    if body.ids:
        q = q.where(CrmNotification.id.in_(body.ids))
    await db.execute(q.values(read_at=utcnow()))
    await db.commit()
    return {"ok": True}
