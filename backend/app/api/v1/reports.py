import io
import csv
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ...core.deps import get_db, require_permission
from ...core.store_scope import allowed_store_ids, store_filter
from ...models.models import DailySubmission, Store, Lead, LostReason, User

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/monthly-summary")
async def monthly_summary(
    start: date = None, end: date = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("reports", "view"),
):
    if not end:
        end = date.today()
    if not start:
        start = end - timedelta(days=30)

    store_q = select(Store).where(Store.is_active == True)
    store_q = store_q.where(store_filter(Store.id, await allowed_store_ids(user, db)))
    stores = (await db.execute(store_q)).scalars().all()
    store_ids = [s.id for s in stores]

    rev_q = select(
        DailySubmission.store_id,
        func.sum(DailySubmission.revenue).label("total_revenue"),
        func.sum(DailySubmission.units_sold).label("total_units"),
    ).where(
        DailySubmission.date >= start, DailySubmission.date <= end,
    )
    rev_q = rev_q.where(DailySubmission.store_id.in_(store_ids))
    rev_q = rev_q.group_by(DailySubmission.store_id)
    revs = (await db.execute(rev_q)).all()

    store_map = {s.id: s for s in stores}
    summary = []
    for r in revs:
        st = store_map.get(r.store_id)
        if st:
            summary.append({
                "store_id": r.store_id,
                "store_name": st.name,
                "revenue": float(r.total_revenue or 0),
                "units": int(r.total_units or 0),
                "target": float(st.monthly_target),
                "achievement": float(r.total_revenue or 0) / float(st.monthly_target) * 100 if st.monthly_target > 0 else 0,
            })
    summary.sort(key=lambda x: x["revenue"], reverse=True)
    return {"start": start, "end": end, "stores": summary}


@router.get("/leaderboard")
async def leaderboard(
    start: date = None, end: date = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("reports", "view"),
):
    if not end:
        end = date.today()
    if not start:
        start = end - timedelta(days=30)

    allowed = await allowed_store_ids(user, db)
    tl_q = select(User).join(Store, Store.team_leader_id == User.id).where(store_filter(Store.id, allowed)).distinct()
    tls = (await db.execute(tl_q)).scalars().all()

    store_q = select(Store).where(Store.is_active == True, store_filter(Store.id, allowed))
    stores = (await db.execute(store_q)).scalars().all()

    results = []
    for tl in tls:
        tl_store_ids = [s.id for s in stores if s.team_leader_id == tl.id]
        if not tl_store_ids:
            continue
        rev_q = select(func.coalesce(func.sum(DailySubmission.revenue), 0)).where(
            DailySubmission.date >= start, DailySubmission.date <= end,
            DailySubmission.store_id.in_(tl_store_ids),
        )
        rev = float((await db.execute(rev_q)).scalar() or 0)
        days = (end - start).days + 1
        target = sum(float(s.monthly_target) * days / 30 for s in stores if s.team_leader_id == tl.id)
        results.append({
            "name": tl.name, "email": tl.email,
            "revenue": rev, "target": target,
            "achievement": (rev / target * 100) if target > 0 else 0,
        })
    results.sort(key=lambda x: x["revenue"], reverse=True)
    return {"start": start, "end": end, "leaderboard": results}


@router.get("/lost-reasons")
async def lost_reason_analysis(
    start: date = None, end: date = None,
    store_id: int = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("reports", "view"),
):
    if not end:
        end = date.today()
    if not start:
        start = end - timedelta(days=30)

    query = select(
        LostReason.reason,
        func.sum(LostReason.count).label("total"),
    ).where(LostReason.date >= start, LostReason.date <= end,
            store_filter(LostReason.store_id, await allowed_store_ids(user, db)))
    if store_id:
        query = query.where(LostReason.store_id == store_id)
    query = query.group_by(LostReason.reason)
    result = await db.execute(query)
    reasons = [{"reason": r.reason, "count": int(r.total or 0)} for r in result.all()]
    reasons.sort(key=lambda x: x["count"], reverse=True)
    total = sum(r["count"] for r in reasons)
    for r in reasons:
        r["percentage"] = (r["count"] / total * 100) if total > 0 else 0
    return {"start": start, "end": end, "reasons": reasons, "total_lost": total}


@router.get("/export/csv")
async def export_csv(
    start: date = None, end: date = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("reports", "export"),
):
    if not end:
        end = date.today()
    if not start:
        start = end - timedelta(days=30)

    store_q = select(Store).where(Store.is_active == True)
    store_q = store_q.where(store_filter(Store.id, await allowed_store_ids(user, db)))
    stores = (await db.execute(store_q)).scalars().all()
    store_ids = [s.id for s in stores]
    store_map = {s.id: s for s in stores}

    sub_q = select(DailySubmission).where(
        DailySubmission.date >= start, DailySubmission.date <= end,
    )
    sub_q = sub_q.where(DailySubmission.store_id.in_(store_ids))
    subs = (await db.execute(sub_q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Store", "Date", "Revenue", "Units Sold", "Walk-ins", "Conversions", "Calls Made"])
    for s in subs:
        st = store_map.get(s.store_id)
        writer.writerow([
            st.name if st else "", s.date, float(s.revenue),
            s.units_sold, s.walk_ins, s.walk_in_conversions, s.calls_made,
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=report_{start}_{end}.csv"},
    )
