from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core.deps import get_db, require_permission, get_user_permissions
from ...core.store_scope import allowed_store_ids, store_filter
from ...models.models import Lead, LeadActivity, LostReason, Store, User
from ...schemas import (
    LeadCreate, LeadUpdate, LeadResponse,
    LeadActivityCreate, LeadActivityResponse,
    LostReasonCreate, LostReasonResponse,
)

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("/", response_model=list[LeadResponse])
async def list_leads(
    store_id: int = None, status_filter: str = None, source: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "view"),
):
    query = select(Lead)
    query = query.where(store_filter(Lead.store_id, await allowed_store_ids(user, db)))
    if store_id:
        query = query.where(Lead.store_id == store_id)
    if status_filter:
        query = query.where(Lead.status == status_filter)
    if source:
        query = query.where(Lead.source == source)
    query = query.order_by(Lead.created_at.desc())
    result = await db.execute(query)
    leads = result.scalars().all()
    store_cache = {}
    user_cache = {}
    out = []
    for l in leads:
        if l.store_id not in store_cache:
            r = await db.execute(select(Store).where(Store.id == l.store_id))
            store_cache[l.store_id] = r.scalar_one_or_none()
        if l.assigned_to and l.assigned_to not in user_cache:
            r = await db.execute(select(User).where(User.id == l.assigned_to))
            user_cache[l.assigned_to] = r.scalar_one_or_none()
        st = store_cache.get(l.store_id)
        asg = user_cache.get(l.assigned_to)
        out.append(LeadResponse(
            id=l.id, store_id=l.store_id, store_name=st.name if st else "",
            source=l.source, name=l.name, phone=l.phone or "",
            status=l.status, stage=l.stage or "",
            assigned_to=l.assigned_to, assignee_name=asg.name if asg else "",
            created_at=l.created_at, last_contacted_at=l.last_contacted_at,
        ))
    return out


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "create"),
):
    lead = Lead(
        store_id=body.store_id, source=body.source, name=body.name,
        phone=body.phone, status=body.status, stage=body.stage,
        assigned_to=body.assigned_to,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    r = await db.execute(select(Store).where(Store.id == lead.store_id))
    st = r.scalar_one_or_none()
    asg_name = ""
    if lead.assigned_to:
        r2 = await db.execute(select(User).where(User.id == lead.assigned_to))
        asg = r2.scalar_one_or_none()
        asg_name = asg.name if asg else ""
    return LeadResponse(
        id=lead.id, store_id=lead.store_id, store_name=st.name if st else "",
        source=lead.source, name=lead.name, phone=lead.phone or "",
        status=lead.status, stage=lead.stage or "",
        assigned_to=lead.assigned_to, assignee_name=asg_name,
        created_at=lead.created_at, last_contacted_at=lead.last_contacted_at,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "view"),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    r = await db.execute(select(Store).where(Store.id == lead.store_id))
    st = r.scalar_one_or_none()
    asg_name = ""
    if lead.assigned_to:
        r2 = await db.execute(select(User).where(User.id == lead.assigned_to))
        asg = r2.scalar_one_or_none()
        asg_name = asg.name if asg else ""
    return LeadResponse(
        id=lead.id, store_id=lead.store_id, store_name=st.name if st else "",
        source=lead.source, name=lead.name, phone=lead.phone or "",
        status=lead.status, stage=lead.stage or "",
        assigned_to=lead.assigned_to, assignee_name=asg_name,
        created_at=lead.created_at, last_contacted_at=lead.last_contacted_at,
    )


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: int, body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "edit"),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    await db.commit()
    await db.refresh(lead)
    r = await db.execute(select(Store).where(Store.id == lead.store_id))
    st = r.scalar_one_or_none()
    return LeadResponse(
        id=lead.id, store_id=lead.store_id, store_name=st.name if st else "",
        source=lead.source, name=lead.name, phone=lead.phone or "",
        status=lead.status, stage=lead.stage or "",
        assigned_to=lead.assigned_to, assignee_name="",
        created_at=lead.created_at, last_contacted_at=lead.last_contacted_at,
    )


@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "delete"),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.delete(lead)
    await db.commit()
    return {"message": "Lead deleted"}


# ── Lead Activities ────────────────────────────────────────────
@router.get("/{lead_id}/activities", response_model=list[LeadActivityResponse])
async def list_activities(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "view"),
):
    result = await db.execute(
        select(LeadActivity).where(LeadActivity.lead_id == lead_id).order_by(LeadActivity.created_at.desc())
    )
    acts = result.scalars().all()
    user_cache = {}
    out = []
    for a in acts:
        if a.created_by and a.created_by not in user_cache:
            r = await db.execute(select(User).where(User.id == a.created_by))
            user_cache[a.created_by] = r.scalar_one_or_none()
        cr = user_cache.get(a.created_by)
        out.append(LeadActivityResponse(
            id=a.id, lead_id=a.lead_id, type=a.type,
            outcome=a.outcome or "", notes=a.notes or "",
            created_by=a.created_by, creator_name=cr.name if cr else "",
            created_at=a.created_at,
        ))
    return out


@router.post("/{lead_id}/activities", response_model=LeadActivityResponse, status_code=status.HTTP_201_CREATED)
async def create_activity(
    lead_id: int, body: LeadActivityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "create"),
):
    act = LeadActivity(
        lead_id=lead_id, type=body.type, outcome=body.outcome,
        notes=body.notes, created_by=user.id,
    )
    db.add(act)
    await db.commit()
    await db.refresh(act)
    return LeadActivityResponse(
        id=act.id, lead_id=act.lead_id, type=act.type,
        outcome=act.outcome or "", notes=act.notes or "",
        created_by=act.created_by, creator_name=user.name,
        created_at=act.created_at,
    )


# ── Lost Reasons ───────────────────────────────────────────────
@router.get("/lost-reasons", response_model=list[LostReasonResponse])
async def list_lost_reasons(
    store_id: int = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "view"),
):
    query = select(LostReason)
    if store_id:
        query = query.where(LostReason.store_id == store_id)
    query = query.where(store_filter(LostReason.store_id, await allowed_store_ids(user, db)))
    result = await db.execute(query.order_by(LostReason.date.desc()))
    return [LostReasonResponse.model_validate(lr) for lr in result.scalars().all()]


@router.post("/lost-reasons", response_model=LostReasonResponse, status_code=status.HTTP_201_CREATED)
async def create_lost_reason(
    body: LostReasonCreate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("leads", "create"),
):
    lr = LostReason(store_id=body.store_id, date=body.date, reason=body.reason, count=body.count)
    db.add(lr)
    await db.commit()
    await db.refresh(lr)
    return LostReasonResponse.model_validate(lr)
