from datetime import date, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ...core.deps import get_db, require_permission
from ...core.store_scope import allowed_store_ids, store_filter
from ...models.models import (
    DailySubmission, Store, KPIWeight, IncentiveBand, GoogleReview, User,
)
from ...schemas import KPIScoreResponse, GoogleReviewCreate, GoogleReviewResponse

router = APIRouter(prefix="/performance", tags=["performance"])


def _resolve_band(score: float, bands: list) -> tuple[str, float]:
    sorted_bands = sorted(bands, key=lambda b: b.min_kpi_score, reverse=True)
    for band in sorted_bands:
        if score >= float(band.min_kpi_score):
            return band.label, float(band.multiplier)
    return "Below Target", 1.0


@router.get("/scores", response_model=list[KPIScoreResponse])
async def get_scores(
    start: date = None, end: date = None,
    store_id: int = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("performance", "view"),
):
    if not end:
        end = date.today()
    if not start:
        start = end - timedelta(days=30)

    weights_q = await db.execute(select(KPIWeight))
    weights = {k.kpi_name: float(k.weight) for k in weights_q.scalars().all()}

    bands_q = await db.execute(select(IncentiveBand))
    bands = bands_q.scalars().all()

    store_q = select(Store).where(Store.is_active == True)
    if store_id:
        store_q = store_q.where(Store.id == store_id)
    store_q = store_q.where(store_filter(Store.id, await allowed_store_ids(user, db)))
    stores = (await db.execute(store_q)).scalars().all()

    results = []
    for store in stores:
        sub_q = await db.execute(
            select(DailySubmission).where(
                DailySubmission.store_id == store.id,
                DailySubmission.date >= start, DailySubmission.date <= end,
            )
        )
        subs = sub_q.scalars().all()
        days = (end - start).days + 1
        scores = {}

        total_rev = sum(float(s.revenue) for s in subs)
        target = float(store.monthly_target) * days / 30
        scores["revenue_vs_target"] = (total_rev / target) if target > 0 else 0

        submission_count = len(subs)
        scores["dsr_submission_rate"] = min(submission_count / days, 1.0) if days > 0 else 0

        total_walk_ins = sum(s.walk_ins for s in subs)
        total_conversions = sum(s.walk_in_conversions for s in subs)
        scores["walk_in_conversion"] = (total_conversions / total_walk_ins) if total_walk_ins > 0 else 0

        scores["cash_management"] = 1.0

        scores["care_plus_attachment"] = 0.0

        total_calls = sum(s.calls_made for s in subs)
        scores["calls_vs_target"] = min(total_calls / (days * 50), 1.0) if days > 0 else 0

        total_stock_sold = sum(s.stock_sold for s in subs)
        total_stock_var = sum(abs(s.stock_variance) for s in subs)
        scores["stock_control"] = max(0, 1.0 - (total_stock_var / max(total_stock_sold, 1)))

        trained_days = sum(1 for s in subs if s.training_done)
        scores["training_compliance"] = trained_days / max(submission_count, 1)

        app_updated_days = sum(1 for s in subs if s.app_updated)
        scores["bp_app_update_rate"] = app_updated_days / max(submission_count, 1)

        total_complaints = sum(s.complaints_in for s in subs)
        total_resolved = sum(s.complaints_resolved for s in subs)
        scores["complaint_resolution"] = (total_resolved / total_complaints) if total_complaints > 0 else 1.0

        total_score = sum(scores.get(k, 0) * v for k, v in weights.items())
        band_label, multiplier = _resolve_band(total_score, bands)

        results.append(KPIScoreResponse(
            store_id=store.id, store_name=store.name,
            period_start=start, period_end=end,
            scores=scores, total_score=total_score,
            incentive_band=band_label, incentive_multiplier=multiplier,
        ))
    return results


@router.get("/google-reviews", response_model=list[GoogleReviewResponse])
async def list_google_reviews(
    store_id: int = None,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("performance", "view"),
):
    query = select(GoogleReview)
    if store_id:
        query = query.where(GoogleReview.store_id == store_id)
    result = await db.execute(query.order_by(GoogleReview.date.desc()))
    return [GoogleReviewResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/google-reviews", response_model=GoogleReviewResponse)
async def create_google_review(
    body: GoogleReviewCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("performance", "create"),
):
    gr = GoogleReview(
        store_id=body.store_id, date=body.date,
        rating=body.rating, total_reviews=body.total_reviews,
        new_reviews=body.new_reviews,
    )
    db.add(gr)
    await db.commit()
    await db.refresh(gr)
    return GoogleReviewResponse.model_validate(gr)
