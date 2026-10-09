from datetime import datetime, date, timedelta, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core.config import settings
from ...core.deps import get_current_user, get_db, require_permission, get_user_permissions
from ...core.store_scope import allowed_store_ids, store_filter
from ...models.models import DailySubmission, Store, User
from ...schemas import DailySubmissionCreate, DailySubmissionUpdate, DailySubmissionResponse

router = APIRouter(prefix="/submissions", tags=["submissions"])


def _can_edit(user: User, submission: DailySubmission) -> bool:
    if any(True for _ in []):
        return True
    now = datetime.now(timezone.utc)
    sub_dt = datetime.combine(submission.date, datetime.min.time()).replace(tzinfo=timezone.utc)
    hours_since = (now - sub_dt).total_seconds() / 3600
    return hours_since <= settings.SAME_DAY_EDIT_WINDOW_HOURS if hasattr(settings, 'SAME_DAY_EDIT_WINDOW_HOURS') else hours_since <= 12


@router.get("/", response_model=list[DailySubmissionResponse])
async def list_submissions(
    store_id: int = None,
    start_date: date = None,
    end_date: date = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # scoped to the caller's stores; reading your own store's submissions
    # needs no page permission (store and role dashboards use it)
    query = select(DailySubmission)
    query = query.where(store_filter(DailySubmission.store_id, await allowed_store_ids(user, db)))
    if store_id:
        query = query.where(DailySubmission.store_id == store_id)
    if start_date:
        query = query.where(DailySubmission.date >= start_date)
    if end_date:
        query = query.where(DailySubmission.date <= end_date)
    query = query.order_by(DailySubmission.date.desc(), DailySubmission.store_id)

    result = await db.execute(query)
    subs = result.scalars().all()
    store_cache = {}
    out = []
    for s in subs:
        if s.store_id not in store_cache:
            r = await db.execute(select(Store).where(Store.id == s.store_id))
            store_cache[s.store_id] = r.scalar_one_or_none()
        st = store_cache.get(s.store_id)
        out.append(DailySubmissionResponse(
            id=s.id, store_id=s.store_id, store_name=st.name if st else "",
            date=s.date, revenue=float(s.revenue), units_sold=s.units_sold,
            care_plus_attached=s.care_plus_attached, new_leads=s.new_leads,
            active_leads=s.active_leads, calls_made=s.calls_made,
            calls_connected=s.calls_connected, walk_ins=s.walk_ins,
            walk_in_conversions=s.walk_in_conversions, staff_on_duty=s.staff_on_duty,
            training_done=s.training_done, training_topic=s.training_topic or "",
            stock_opening=s.stock_opening, stock_received=s.stock_received,
            stock_sold=s.stock_sold, stock_closing=s.stock_closing,
            stock_variance=s.stock_variance, cash_opening=float(s.cash_opening),
            cash_sales=float(s.cash_sales), bank_deposit=float(s.bank_deposit),
            petty_cash_note=s.petty_cash_note or "",
            cash_closing=float(s.cash_closing), installations=s.installations,
            service_calls=s.service_calls, complaints_in=s.complaints_in,
            complaints_resolved=s.complaints_resolved, app_updated=s.app_updated,
            notes=s.notes or "", google_review_rating=s.google_review_rating,
            submitted_by=s.submitted_by, submitted_at=s.submitted_at,
            created_at=s.created_at,
        ))
    return out


@router.post("/", response_model=DailySubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_submission(
    body: DailySubmissionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("operations", "create"),
):
    existing = await db.execute(
        select(DailySubmission)
        .where(DailySubmission.store_id == body.store_id, DailySubmission.date == body.date)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Submission already exists for this store and date")

    sub = DailySubmission(
        store_id=body.store_id, date=body.date,
        revenue=body.revenue, units_sold=body.units_sold,
        care_plus_attached=body.care_plus_attached,
        new_leads=body.new_leads, active_leads=body.active_leads,
        calls_made=body.calls_made, calls_connected=body.calls_connected,
        walk_ins=body.walk_ins, walk_in_conversions=body.walk_in_conversions,
        staff_on_duty=body.staff_on_duty, training_done=body.training_done,
        training_topic=body.training_topic, stock_opening=body.stock_opening,
        stock_received=body.stock_received, stock_sold=body.stock_sold,
        stock_closing=body.stock_closing, stock_variance=body.stock_variance,
        cash_opening=body.cash_opening, cash_sales=body.cash_sales,
        bank_deposit=body.bank_deposit, petty_cash_note=body.petty_cash_note,
        cash_closing=body.cash_closing, installations=body.installations,
        service_calls=body.service_calls, complaints_in=body.complaints_in,
        complaints_resolved=body.complaints_resolved, app_updated=body.app_updated,
        notes=body.notes, google_review_rating=body.google_review_rating,
        submitted_by=user.id, submitted_at=datetime.now(timezone.utc),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    r = await db.execute(select(Store).where(Store.id == sub.store_id))
    st = r.scalar_one_or_none()
    return DailySubmissionResponse(
        id=sub.id, store_id=sub.store_id, store_name=st.name if st else "",
        date=sub.date, revenue=float(sub.revenue), units_sold=sub.units_sold,
        care_plus_attached=sub.care_plus_attached, new_leads=sub.new_leads,
        active_leads=sub.active_leads, calls_made=sub.calls_made,
        calls_connected=sub.calls_connected, walk_ins=sub.walk_ins,
        walk_in_conversions=sub.walk_in_conversions, staff_on_duty=sub.staff_on_duty,
        training_done=sub.training_done, training_topic=sub.training_topic or "",
        stock_opening=sub.stock_opening, stock_received=sub.stock_received,
        stock_sold=sub.stock_sold, stock_closing=sub.stock_closing,
        stock_variance=sub.stock_variance, cash_opening=float(sub.cash_opening),
        cash_sales=float(sub.cash_sales), bank_deposit=float(sub.bank_deposit),
        petty_cash_note=sub.petty_cash_note or "",
        cash_closing=float(sub.cash_closing), installations=sub.installations,
        service_calls=sub.service_calls, complaints_in=sub.complaints_in,
        complaints_resolved=sub.complaints_resolved, app_updated=sub.app_updated,
        notes=sub.notes or "", google_review_rating=sub.google_review_rating,
        submitted_by=sub.submitted_by, submitted_at=sub.submitted_at,
        created_at=sub.created_at,
    )


@router.get("/{sub_id}", response_model=DailySubmissionResponse)
async def get_submission(
    sub_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("operations", "view"),
):
    result = await db.execute(select(DailySubmission).where(DailySubmission.id == sub_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    r = await db.execute(select(Store).where(Store.id == sub.store_id))
    st = r.scalar_one_or_none()
    return DailySubmissionResponse(
        id=sub.id, store_id=sub.store_id, store_name=st.name if st else "",
        date=sub.date, revenue=float(sub.revenue), units_sold=sub.units_sold,
        care_plus_attached=sub.care_plus_attached, new_leads=sub.new_leads,
        active_leads=sub.active_leads, calls_made=sub.calls_made,
        calls_connected=sub.calls_connected, walk_ins=sub.walk_ins,
        walk_in_conversions=sub.walk_in_conversions, staff_on_duty=sub.staff_on_duty,
        training_done=sub.training_done, training_topic=sub.training_topic or "",
        stock_opening=sub.stock_opening, stock_received=sub.stock_received,
        stock_sold=sub.stock_sold, stock_closing=sub.stock_closing,
        stock_variance=sub.stock_variance, cash_opening=float(sub.cash_opening),
        cash_sales=float(sub.cash_sales), bank_deposit=float(sub.bank_deposit),
        petty_cash_note=sub.petty_cash_note or "",
        cash_closing=float(sub.cash_closing), installations=sub.installations,
        service_calls=sub.service_calls, complaints_in=sub.complaints_in,
        complaints_resolved=sub.complaints_resolved, app_updated=sub.app_updated,
        notes=sub.notes or "", google_review_rating=sub.google_review_rating,
        submitted_by=sub.submitted_by, submitted_at=sub.submitted_at,
        created_at=sub.created_at,
    )


@router.put("/{sub_id}", response_model=DailySubmissionResponse)
async def update_submission(
    sub_id: int,
    body: DailySubmissionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("operations", "edit"),
):
    result = await db.execute(select(DailySubmission).where(DailySubmission.id == sub_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if not _can_edit(user, sub):
        raise HTTPException(
            status_code=403,
            detail=f"Edit window expired. Only admins can edit submissions older than {settings.SAME_DAY_EDIT_WINDOW_HOURS if hasattr(settings, 'SAME_DAY_EDIT_WINDOW_HOURS') else 12}h"
        )
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sub, field, value)
    await db.commit()
    await db.refresh(sub)
    r = await db.execute(select(Store).where(Store.id == sub.store_id))
    st = r.scalar_one_or_none()
    return DailySubmissionResponse(
        id=sub.id, store_id=sub.store_id, store_name=st.name if st else "",
        date=sub.date, revenue=float(sub.revenue), units_sold=sub.units_sold,
        care_plus_attached=sub.care_plus_attached, new_leads=sub.new_leads,
        active_leads=sub.active_leads, calls_made=sub.calls_made,
        calls_connected=sub.calls_connected, walk_ins=sub.walk_ins,
        walk_in_conversions=sub.walk_in_conversions, staff_on_duty=sub.staff_on_duty,
        training_done=sub.training_done, training_topic=sub.training_topic or "",
        stock_opening=sub.stock_opening, stock_received=sub.stock_received,
        stock_sold=sub.stock_sold, stock_closing=sub.stock_closing,
        stock_variance=sub.stock_variance, cash_opening=float(sub.cash_opening),
        cash_sales=float(sub.cash_sales), bank_deposit=float(sub.bank_deposit),
        petty_cash_note=sub.petty_cash_note or "",
        cash_closing=float(sub.cash_closing), installations=sub.installations,
        service_calls=sub.service_calls, complaints_in=sub.complaints_in,
        complaints_resolved=sub.complaints_resolved, app_updated=sub.app_updated,
        notes=sub.notes or "", google_review_rating=sub.google_review_rating,
        submitted_by=sub.submitted_by, submitted_at=sub.submitted_at,
        created_at=sub.created_at,
    )
