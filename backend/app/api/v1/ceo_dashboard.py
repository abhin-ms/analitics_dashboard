import asyncio
import re
import logging
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ...core.deps import get_db, require_permission, require_admin_tier
from ...models.models import (
    Store, User, DailySubmission, Lead, Campaign, Task, Investment,
    MarketingMetrics, StoreStaff, InternationalStore, StrategicInsight,
    GoogleReview, DailyStoreTracker, StoreDashboardSnapshot,
)
from ...schemas import (
    CEOOverviewResponse, CEOOpsResponse, CEOTLResponse, CEOIntlResponse,
    CEOMarketingResponse, CEOReviewsResponse, CEOPeopleResponse, CEOActionsResponse,
    BulkImportRequest, MarketingMetricsResponse, StoreStaffResponse,
    InternationalStoreResponse, StrategicInsightResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ceo-dashboard", tags=["ceo-dashboard"])


def _month_str(d: date) -> str:
    return d.strftime("%Y-%m")


def _month_range(month: str) -> tuple[date, date]:
    """Return (start_date, end_date) inclusive for a "YYYY-MM" month string."""
    start_date = date.fromisoformat(f"{month}-01")
    if start_date.month == 12:
        next_month_start = date(start_date.year + 1, 1, 1)
    else:
        next_month_start = date(start_date.year, start_date.month + 1, 1)
    return start_date, next_month_start - timedelta(days=1)


async def _get_month(db: AsyncSession, month: str):
    return month


# ── Overview Tab ────────────────────────────────────────────────────
@router.get("/overview")
async def ceo_overview(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    if not month:
        month = _month_str(date.today())

    # Get all stores with their TL names
    stores = (await db.execute(select(Store).where(Store.is_active == True))).scalars().all()
    store_ids = [s.id for s in stores]

    # Revenue data for the month
    start_date, end_date = _month_range(month)

    # Store achievements
    store_achievements = []
    total_revenue = 0
    total_target = 0
    for s in stores:
        rev_q = select(func.coalesce(func.sum(DailySubmission.revenue), 0)).where(
            DailySubmission.store_id == s.id,
            DailySubmission.date >= start_date,
            DailySubmission.date <= end_date,
        )
        rev = float((await db.execute(rev_q)).scalar() or 0)
        tgt = float(s.monthly_target or 0)
        ach = (rev / tgt * 100) if tgt > 0 else 0
        total_revenue += rev
        total_target += tgt

        # Get TL name
        tl_name = "Unassigned"
        if s.team_leader_id:
            r = await db.execute(select(User.name).where(User.id == s.team_leader_id))
            tl_name = r.scalar() or "Unassigned"

        # Walk-ins from submissions
        wi_q = select(func.coalesce(func.sum(DailySubmission.walk_ins), 0)).where(
            DailySubmission.store_id == s.id,
            DailySubmission.date >= start_date,
            DailySubmission.date <= end_date,
        )
        walkins = int((await db.execute(wi_q)).scalar() or 0)

        sales_q = select(func.coalesce(func.sum(DailySubmission.walk_in_conversions), 0)).where(
            DailySubmission.store_id == s.id,
            DailySubmission.date >= start_date,
            DailySubmission.date <= end_date,
        )
        sales = int((await db.execute(sales_q)).scalar() or 0)

        store_achievements.append({
            "store": s.name,
            "tl": tl_name,
            "region": "",
            "mtd": rev,
            "target": tgt,
            "ach_pct": round(ach, 1),
            "walkins": walkins,
            "sales": sales,
            "conv_pct": round(sales / walkins * 100) if walkins > 0 else 0,
        })

    store_achievements.sort(key=lambda x: x["ach_pct"], reverse=True)

    # TL achievements
    tl_map = {}
    for sa in store_achievements:
        tl = sa["tl"]
        if tl not in tl_map:
            tl_map[tl] = {"name": tl, "target": 0, "achieved": 0, "walkins": 0, "conv": 0, "stores": []}
        tl_map[tl]["target"] += sa["target"]
        tl_map[tl]["achieved"] += sa["mtd"]
        tl_map[tl]["walkins"] += sa["walkins"]
        tl_map[tl]["conv"] += sa["sales"]
        tl_map[tl]["stores"].append(sa["store"])
    tl_list = sorted(tl_map.values(), key=lambda x: x["achieved"], reverse=True)
    for tl in tl_list:
        tl["ach_pct"] = round(tl["achieved"] / tl["target"] * 100) if tl["target"] > 0 else 0
        tl["conv_pct"] = round(tl["conv"] / tl["walkins"] * 100) if tl["walkins"] > 0 else 0

    # RAG distribution
    rag = {"green": 0, "amber": 0, "red": 0}
    for sa in store_achievements:
        if sa["ach_pct"] >= 65:
            rag["green"] += 1
        elif sa["ach_pct"] >= 35:
            rag["amber"] += 1
        else:
            rag["red"] += 1

    # Marketing data for WA walkins top
    mkt_q = select(MarketingMetrics).where(MarketingMetrics.month == month)
    mkt_data = (await db.execute(mkt_q)).scalars().all()
    wa_top = []
    for m in mkt_data:
        store_q = select(Store.name).where(Store.id == m.store_id)
        sname = (await db.execute(store_q)).scalar() or "Unknown"
        wa_top.append({"store": sname, "wa_walkins": m.wa_walkins or 0})
    wa_top.sort(key=lambda x: x["wa_walkins"], reverse=True)

    # International overview
    intl_q = select(InternationalStore).where(InternationalStore.month == month)
    intl_data = (await db.execute(intl_q)).scalars().all()
    intl_summary = {}
    for i in intl_data:
        key = i.region
        if key not in intl_summary:
            intl_summary[key] = {"region": key, "country": i.country, "target": 0, "actual": 0, "stores": 0}
        intl_summary[key]["target"] += float(i.target or 0)
        intl_summary[key]["actual"] += float(i.actual or 0)
        intl_summary[key]["stores"] += 1
    intl_list = list(intl_summary.values())
    for item in intl_list:
        item["ach_pct"] = round(item["actual"] / item["target"] * 100) if item["target"] > 0 else 0

    # Insights
    ins_q = select(StrategicInsight).where(
        StrategicInsight.month == month,
        StrategicInsight.section == "overview",
    ).order_by(StrategicInsight.sort_order)
    insights_db = (await db.execute(ins_q)).scalars().all()
    insights = [{"category": i.category, "title": i.title, "description": i.description, "action_tag": i.action_tag} for i in insights_db]

    overall_ach = round(total_revenue / total_target * 100, 1) if total_target > 0 else 0

    return {
        "kpis": {
            "total_revenue": total_revenue,
            "total_target": total_target,
            "achievement_pct": overall_ach,
            "total_walkins": sum(sa["walkins"] for sa in store_achievements),
            "total_conversions": sum(sa["sales"] for sa in store_achievements),
            "conv_pct": round(sum(sa["sales"] for sa in store_achievements) / max(sum(sa["walkins"] for sa in store_achievements), 1) * 100),
            "store_count": len(stores),
            "tl_count": len(tl_list),
        },
        "store_achievements": store_achievements,
        "tl_achievements": [{"name": t["name"], "ach_pct": t["ach_pct"], "target": t["target"], "achieved": t["achieved"], "stores": t["stores"]} for t in tl_list],
        "rag_distribution": rag,
        "intl_overview": intl_list,
        "wa_walkins_top": wa_top[:12],
        "insights": insights,
    }


# ── Marketing Tab ──────────────────────────────────────────────────
@router.get("/marketing")
async def ceo_marketing(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    if not month:
        month = _month_str(date.today())

    mkt_q = select(MarketingMetrics).where(MarketingMetrics.month == month)
    mkt_data = (await db.execute(mkt_q)).scalars().all()

    store_table = []
    for m in mkt_data:
        store_q = select(Store.name).where(Store.id == m.store_id)
        sname = (await db.execute(store_q)).scalar() or "Unknown"

        tl_q = select(Store.team_leader_id).where(Store.id == m.store_id)
        tl_id = (await db.execute(tl_q)).scalar()
        tl_name = "—"
        if tl_id:
            r = await db.execute(select(User.name).where(User.id == tl_id))
            tl_name = r.scalar() or "—"

        mc_pct = round((m.ig_manychat_handled or 0) / (m.ig_dms_received or 1) * 100) if (m.ig_dms_received or 0) > 0 else None
        view_pct = round((m.ig_views or 0) / 1000000 * 100) if (m.ig_views or 0) > 0 else None

        store_table.append({
            "store": sname, "tl": tl_name,
            "ig_videos": m.ig_videos_posted, "ig_views": m.ig_views, "view_pct": view_pct,
            "ig_followers": m.ig_followers, "ig_new_followers": m.ig_new_followers,
            "ig_likes": m.ig_likes, "ig_comments": m.ig_comments,
            "ig_dms": m.ig_dms_received, "ig_manychat": m.ig_manychat_handled, "mc_pct": mc_pct,
            "ig_posts": m.ig_posts,
            "wa_walkins": m.wa_walkins,
            "google_rating": m.google_rating, "google_new_reviews": m.google_new_reviews,
            "review_response": m.google_review_response,
        })

    # KPIs
    ig_views_stores = [s for s in store_table if s["ig_views"] and s["ig_views"] > 0]
    wa_stores = sorted(store_table, key=lambda x: x["wa_walkins"], reverse=True)
    dms_stores = [s for s in store_table if s["ig_dms"] and s["ig_dms"] > 0]
    no_ig = [s for s in store_table if s["ig_views"] is None]

    kpis = {
        "highest_ig_views": max(ig_views_stores, key=lambda x: x["ig_views"])["store"] if ig_views_stores else "—",
        "highest_ig_views_count": max((s["ig_views"] or 0) for s in store_table),
        "most_wa_walkins": wa_stores[0]["store"] if wa_stores else "—",
        "most_wa_count": wa_stores[0]["wa_walkins"] if wa_stores else 0,
        "most_dms": max(dms_stores, key=lambda x: x["ig_dms"])["store"] if dms_stores else "—",
        "most_dms_count": max((s["ig_dms"] or 0) for s in store_table),
        "no_ig_count": len(no_ig),
    }

    # Insights
    ins_q = select(StrategicInsight).where(
        StrategicInsight.month == month,
        StrategicInsight.section == "marketing",
    ).order_by(StrategicInsight.sort_order)
    insights_db = (await db.execute(ins_q)).scalars().all()
    insights = [{"category": i.category, "title": i.title, "description": i.description, "action_tag": i.action_tag} for i in insights_db]

    return {"kpis": kpis, "store_table": store_table, "insights": insights}


# ── Reviews Tab ────────────────────────────────────────────────────
@router.get("/reviews")
async def ceo_reviews(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    if not month:
        month = _month_str(date.today())

    mkt_q = select(MarketingMetrics).where(MarketingMetrics.month == month)
    mkt_data = (await db.execute(mkt_q)).scalars().all()

    store_table = []
    for m in mkt_data:
        if m.google_rating is None:
            continue
        store_q = select(Store.name).where(Store.id == m.store_id)
        sname = (await db.execute(store_q)).scalar() or "Unknown"
        tl_q = select(Store.team_leader_id).where(Store.id == m.store_id)
        tl_id = (await db.execute(tl_q)).scalar()
        tl_name = "—"
        if tl_id:
            r = await db.execute(select(User.name).where(User.id == tl_id))
            tl_name = r.scalar() or "—"
        store_table.append({
            "store": sname, "tl": tl_name,
            "rating": m.google_rating, "new_reviews": m.google_new_reviews or 0,
            "response": m.google_review_response,
        })

    store_table.sort(key=lambda x: x["rating"], reverse=True)

    kpis = {
        "best_rating": store_table[0]["store"] if store_table else "—",
        "best_rating_value": store_table[0]["rating"] if store_table else 0,
        "most_reviewed": max(store_table, key=lambda x: x["new_reviews"])["store"] if store_table else "—",
        "most_reviewed_count": max((s["new_reviews"] for s in store_table), default=0),
        "not_responding": len([s for s in store_table if s["response"] == "No"]),
    }

    ins_q = select(StrategicInsight).where(
        StrategicInsight.month == month,
        StrategicInsight.section == "reviews",
    ).order_by(StrategicInsight.sort_order)
    insights_db = (await db.execute(ins_q)).scalars().all()
    insights = [{"category": i.category, "title": i.title, "description": i.description, "action_tag": i.action_tag} for i in insights_db]

    return {"kpis": kpis, "store_table": store_table, "insights": insights}


# ── People Tab ─────────────────────────────────────────────────────
@router.get("/people")
async def ceo_people(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    if not month:
        month = _month_str(date.today())

    staff_q = select(StoreStaff).where(StoreStaff.month == month)
    staff_data = (await db.execute(staff_q)).scalars().all()

    store_table = []
    for s in staff_data:
        store_q = select(Store.name).where(Store.id == s.store_id)
        sname = (await db.execute(store_q)).scalar() or "Unknown"
        tl_q = select(Store.team_leader_id).where(Store.id == s.store_id)
        tl_id = (await db.execute(tl_q)).scalar()
        tl_name = "—"
        if tl_id:
            r = await db.execute(select(User.name).where(User.id == tl_id))
            tl_name = r.scalar() or "—"

        tgt_q = select(Store.monthly_target).where(Store.id == s.store_id)
        target = float((await db.execute(tgt_q)).scalar() or 0)

        store_table.append({
            "store": sname, "tl": tl_name, "manager": s.manager_name,
            "accommodation": s.has_accommodation, "staff": s.staff_count,
            "total": s.total_headcount, "resignation_risk": s.resignation_risk,
            "training": s.training_active, "target": target, "notes": s.notes,
        })

    total_staff = sum(s["total"] for s in store_table)
    risk_count = len([s for s in store_table if s["resignation_risk"] > 0])
    training_count = len([s for s in store_table if s["training"]])
    hiring_count = len([s for s in store_table if s["total"] < 2])

    return {
        "kpis": {"total_staff": total_staff, "resignation_risk": risk_count, "in_training": training_count, "need_hire": hiring_count},
        "store_table": store_table,
    }


# ── International Tab ──────────────────────────────────────────────
@router.get("/international")
async def ceo_international(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    if not month:
        month = _month_str(date.today())

    intl_q = select(InternationalStore).where(InternationalStore.month == month)
    intl_data = (await db.execute(intl_q)).scalars().all()

    stores = []
    for i in intl_data:
        pct = round(float(i.actual or 0) / float(i.target or 1) * 100) if i.target else None
        stores.append({
            "id": i.id, "name": i.name, "country": i.country, "region": i.region,
            "target": float(i.target or 0), "actual": float(i.actual or 0), "pct": pct,
        })

    # Country summary
    country_map = {}
    for s in stores:
        key = s["country"]
        if key not in country_map:
            country_map[key] = {"country": key, "target": 0, "actual": 0, "stores": 0}
        country_map[key]["target"] += s["target"]
        country_map[key]["actual"] += s["actual"]
        country_map[key]["stores"] += 1
    country_cards = list(country_map.values())
    for c in country_cards:
        c["pct"] = round(c["actual"] / c["target"] * 100) if c["target"] > 0 else 0

    total_target = sum(c["target"] for c in country_cards)
    total_actual = sum(c["actual"] for c in country_cards)
    country_cards.append({
        "country": "International Total", "target": total_target, "actual": total_actual,
        "pct": round(total_actual / total_target * 100) if total_target > 0 else 0,
        "stores": len(stores),
    })

    ins_q = select(StrategicInsight).where(
        StrategicInsight.month == month,
        StrategicInsight.section == "intl",
    ).order_by(StrategicInsight.sort_order)
    insights_db = (await db.execute(ins_q)).scalars().all()
    insights = [{"category": i.category, "title": i.title, "description": i.description, "action_tag": i.action_tag} for i in insights_db]

    return {"country_cards": country_cards, "stores": stores, "insights": insights}


# ── Actions Tab ────────────────────────────────────────────────────
@router.get("/actions")
async def ceo_actions(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    if not month:
        month = _month_str(date.today())

    ins_q = select(StrategicInsight).where(StrategicInsight.month == month).order_by(StrategicInsight.sort_order)
    all_insights = (await db.execute(ins_q)).scalars().all()

    critical = [{"title": i.title, "description": i.description, "assigned_to": i.assigned_to, "action": i.action_tag, "deadline": i.deadline} for i in all_insights if i.priority == "critical"]
    high = [{"title": i.title, "description": i.description, "assigned_to": i.assigned_to, "action": i.action_tag, "deadline": i.deadline} for i in all_insights if i.priority == "high"]
    strategic = [{"title": i.title, "description": i.description, "assigned_to": i.assigned_to, "action": i.action_tag, "deadline": i.deadline} for i in all_insights if i.priority == "strategic"]

    return {"critical": critical, "high": high, "strategic": strategic}


@router.get("/insight-stats")
async def ceo_insight_stats(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    """How many auto-detected issues (see insight_engine.py) were raised
    this month, how many got resolved, and the average time to resolve —
    the measurable feedback-loop signal for whether the insight engine is
    catching real, fixable problems."""
    if not month:
        month = _month_str(date.today())
    from ...services.insight_engine import get_insight_stats
    return await get_insight_stats(db, month)


# ── Sheets Data (from DB) ──────────────────────────────────────────
@router.get("/sheets-data")
async def ceo_sheets_data(
    tab: str = "all",
    month: str = None,
    start: str = None,
    end: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    """Fetch data from the database (synced from Google Sheets every 1 min).
    Scoped to an explicit start/end range if given, else one calendar month
    (month param, or the current month by default) — start/end lets the
    frontend request a day, a quarter, or any custom range with the same
    endpoint."""
    try:
        if tab == "ops":
            return {"ops_data": await _get_ops_data(db, month, start, end)}
        elif tab == "config":
            return {"store_config": await _get_store_config(db), "store_config_v2": await _get_store_config_v2(db)}
        elif tab == "staff":
            return {"staff": await _get_staff(db)}
        elif tab == "intl_staff":
            return {"intl_staff": await _get_intl_staff(db)}
        elif tab == "reviews":
            return {"reviews": await _get_reviews(db)}
        elif tab == "gr_plan":
            return {"gr_action_plan": await _get_gr_action_plan(db)}
        elif tab == "tl_report":
            return {"tl_report": []}
        elif tab == "daily_tracker":
            return {"daily_tracker": await _get_daily_tracker(db, month, start, end)}
        elif tab == "tracker_months":
            return {"months": await _get_tracker_months(db)}
        elif tab == "store_dashboard_snap":
            return {"store_dashboard": await _get_store_dashboard_snap(db)}
        else:
            return {
                "ops_data": await _get_ops_data(db, month, start, end),
                "store_config": await _get_store_config(db),
                "store_config_v2": await _get_store_config_v2(db),
                "staff": await _get_staff(db),
                "intl_staff": await _get_intl_staff(db),
                "reviews": await _get_reviews(db),
                "gr_action_plan": await _get_gr_action_plan(db),
                "tl_report": [],
                "daily_tracker": await _get_daily_tracker(db, month, start, end),
                "store_dashboard": await _get_store_dashboard_snap(db),
            }
    except Exception as e:
        logger.exception("ceo_sheets_data failed")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to load dashboard data")


def _resolve_range(month: str = None, start: str = None, end: str = None) -> tuple[date, date]:
    if start and end:
        return date.fromisoformat(start), date.fromisoformat(end)
    if not month:
        month = _month_str(date.today())
    return _month_range(month)


async def _get_ops_data(db: AsyncSession, month: str = None, start: str = None, end: str = None) -> list[dict]:
    start_date, end_date = _resolve_range(month, start, end)
    days_in_range = (end_date - start_date).days + 1

    result = await db.execute(
        select(DailySubmission, Store, User.name.label("tl_name"))
        .join(Store, DailySubmission.store_id == Store.id)
        .outerjoin(User, Store.team_leader_id == User.id)
        .where(DailySubmission.date >= start_date, DailySubmission.date <= end_date)
        .order_by(DailySubmission.date.desc())
    )
    rows = result.all()
    seen_stores: set = set()
    out = []
    for sub, store, tl_name in rows:
        store_name = store.name
        is_first = store_name not in seen_stores
        seen_stores.add(store_name)
        out.append({
            "date": str(sub.date),
            "tl": tl_name or "Unassigned",
            "store": store_name,
            "country": "India",
            "revenue": float(sub.revenue or 0),
            # Store.monthly_target is a single static figure (no per-month
            # history), so it's prorated by the requested range length and
            # attached once per store (not once per day) — otherwise summing
            # this field per date/store would multiply it by however many
            # days that store appears in the range.
            "monthly_target": float(store.monthly_target or 0) * days_in_range / 30 if is_first else 0,
            "units_sold": sub.units_sold or 0,
            "new_leads": sub.new_leads or 0,
            "active_leads": sub.active_leads or 0,
            "calls_made": sub.calls_made or 0,
            "calls_connected": sub.calls_connected or 0,
            "walk_ins": sub.walk_ins or 0,
            "walk_in_conversions": sub.walk_in_conversions or 0,
            "care_attached": sub.care_plus_attached or 0,
        })
    return out


async def _get_store_config(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Store, User.name.label("tl_name"))
        .outerjoin(User, Store.team_leader_id == User.id)
        .where(Store.is_active == True)
    )
    rows = result.all()
    return [
        {
            "tl": tl_name or "",
            "store": store.name,
            "country": "India",
            "monthly_target": float(store.monthly_target or 0),
            "breakeven_rev": float(store.breakeven_revenue or 0),
            "profitability_target": float(store.profitability_target or 0),
            "fixed_costs": float(store.fixed_costs or 0),
            "variable_cost_pct": str(store.variable_cost_pct or 0),
            "active": "Y" if store.is_active else "N",
        }
        for store, tl_name in rows
    ]


async def _get_store_config_v2(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Store, User.name.label("tl_name"))
        .outerjoin(User, Store.team_leader_id == User.id)
        .where(Store.is_active == True)
    )
    rows = result.all()
    return [
        {
            "store": store.name,
            "manager": tl_name or "",
            "daily_target": float(store.daily_target or 0),
            "monthly_target": float(store.monthly_target or 0),
        }
        for store, tl_name in rows
    ]


async def _get_staff(db: AsyncSession) -> list[dict]:
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    result = await db.execute(
        select(StoreStaff, Store.name.label("store_name"))
        .join(Store, StoreStaff.store_id == Store.id)
        .where(StoreStaff.month == current_month)
    )
    rows = result.all()
    return [
        {
            "store": store_name,
            "manager": ss.manager_name,
            "has_accommodation": ss.has_accommodation,
            "staff_count": ss.staff_count,
            "resource_required": 0,
            "training": ss.training_active,
            "notes": ss.notes or "",
            "tl": "",
        }
        for ss, store_name in rows
    ]


async def _get_intl_staff(db: AsyncSession) -> list[dict]:
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    result = await db.execute(
        select(InternationalStore).where(InternationalStore.month == current_month)
    )
    stores = result.scalars().all()
    return [
        {
            "store": s.name,
            "sales": "",
            "total": s.actual or 0,
            "resource_required": 0,
            "training": False,
            "notes": "",
            "tl": "",
            "target": float(s.target) if s.target else None,
        }
        for s in stores
    ]


async def _get_reviews(db: AsyncSession) -> list[dict]:
    from datetime import date as dt_date
    result = await db.execute(
        select(GoogleReview, Store)
        .join(Store, GoogleReview.store_id == Store.id)
        .where(GoogleReview.date == dt_date.today())
    )
    rows = result.all()
    return [
        {
            "store": store.name,
            "rating": gr.rating,
            "total_reviews": gr.total_reviews,
            "current_rating": gr.rating,
            "current_total_reviews": gr.total_reviews,
            "new_reviews": gr.new_reviews,
        }
        for gr, store in rows
    ]


async def _get_gr_action_plan(db: AsyncSession) -> list[dict]:
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    result = await db.execute(
        select(StrategicInsight)
        .where(StrategicInsight.month == current_month, StrategicInsight.section == "reviews")
    )
    insights = result.scalars().all()
    return [
        {
            "store": si.title.replace("GR Action: ", ""),
            "tier": si.category,
            "current_rating": "",
            "current_reviews": None,
            "reviews_needed": None,
            "weekly_target": "",
            "timeline": "",
            "root_cause": si.description.split("Cause: ")[1] if "Cause: " in si.description else "",
            "actions": si.action_tag or "",
            "checklist": si.assigned_to or "",
        }
        for si in insights
    ]


# ── Import Endpoints ───────────────────────────────────────────────
@router.post("/import/marketing")
async def import_marketing(
    body: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("settings", "edit"),
):
    count = 0
    for row in body.data:
        store_name = row.get("store", "")
        store_q = select(Store).where(Store.name == store_name)
        store = (await db.execute(store_q)).scalar_one_or_none()
        if not store:
            # Try partial match
            store_q = select(Store).where(Store.name.ilike(f"%{store_name}%"))
            store = (await db.execute(store_q)).scalar_one_or_none()
        if not store:
            continue

        existing_q = select(MarketingMetrics).where(
            MarketingMetrics.store_id == store.id,
            MarketingMetrics.month == body.month,
        )
        existing = (await db.execute(existing_q)).scalar_one_or_none()

        data = {
            "ig_videos_posted": row.get("ig_videos_posted"),
            "ig_views": row.get("ig_views"),
            "ig_followers": row.get("ig_followers"),
            "ig_new_followers": row.get("ig_new_followers"),
            "ig_likes": row.get("ig_likes"),
            "ig_comments": row.get("ig_comments"),
            "ig_dms_received": row.get("ig_dms_received"),
            "ig_manychat_handled": row.get("ig_manychat_handled"),
            "ig_posts": row.get("ig_posts"),
            "wa_walkins": row.get("wa_walkins", 0),
            "google_rating": row.get("google_rating"),
            "google_new_reviews": row.get("google_new_reviews"),
            "google_review_response": row.get("google_review_response", ""),
        }

        if existing:
            for k, v in data.items():
                if v is not None:
                    setattr(existing, k, v)
        else:
            mm = MarketingMetrics(store_id=store.id, month=body.month, **{k: v for k, v in data.items() if v is not None})
            db.add(mm)
        count += 1

    await db.commit()
    return {"imported": count, "month": body.month}


@router.post("/import/staff")
async def import_staff(
    body: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("settings", "edit"),
):
    count = 0
    for row in body.data:
        store_name = row.get("store", "")
        store_q = select(Store).where(Store.name.ilike(f"%{store_name}%"))
        store = (await db.execute(store_q)).scalar_one_or_none()
        if not store:
            continue

        existing_q = select(StoreStaff).where(
            StoreStaff.store_id == store.id,
            StoreStaff.month == body.month,
        )
        existing = (await db.execute(existing_q)).scalar_one_or_none()

        data = {
            "manager_name": row.get("manager_name", ""),
            "staff_count": row.get("staff_count", 0),
            "total_headcount": row.get("total_headcount", 0),
            "has_accommodation": row.get("has_accommodation", False),
            "resignation_risk": row.get("resignation_risk", 0),
            "training_active": row.get("training_active", False),
            "notes": row.get("notes", ""),
        }

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
        else:
            ss = StoreStaff(store_id=store.id, month=body.month, **data)
            db.add(ss)
        count += 1

    await db.commit()
    return {"imported": count, "month": body.month}


@router.post("/import/international")
async def import_international(
    body: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("settings", "edit"),
):
    count = 0
    for row in body.data:
        existing_q = select(InternationalStore).where(
            InternationalStore.name == row.get("name", ""),
            InternationalStore.month == body.month,
        )
        existing = (await db.execute(existing_q)).scalar_one_or_none()

        data = {
            "name": row.get("name", ""),
            "country": row.get("country", ""),
            "region": row.get("region", ""),
            "target": row.get("target"),
            "actual": row.get("actual", 0),
        }

        if existing:
            for k, v in data.items():
                if v is not None:
                    setattr(existing, k, v)
        else:
            ist = InternationalStore(month=body.month, **data)
            db.add(ist)
        count += 1

    await db.commit()
    return {"imported": count, "month": body.month}


@router.post("/import/insights")
async def import_insights(
    body: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("settings", "edit"),
):
    # Delete existing insights for this month before importing
    del_q = select(StrategicInsight).where(StrategicInsight.month == body.month)
    existing = (await db.execute(del_q)).scalars().all()
    for e in existing:
        await db.delete(e)

    count = 0
    for row in body.data:
        insight = StrategicInsight(
            month=body.month,
            category=row.get("category", "info"),
            title=row.get("title", ""),
            description=row.get("description", ""),
            action_tag=row.get("action_tag", ""),
            assigned_to=row.get("assigned_to", ""),
            section=row.get("section", "overview"),
            priority=row.get("priority", "high"),
            deadline=row.get("deadline", ""),
            sort_order=row.get("sort_order", 0),
        )
        db.add(insight)
        count += 1

    await db.commit()
    return {"imported": count, "month": body.month}


async def _get_daily_tracker(db: AsyncSession, month: str = None, start: str = None, end: str = None) -> list[dict]:
    start_date, end_date = _resolve_range(month, start, end)

    result = await db.execute(
        select(DailyStoreTracker)
        .where(DailyStoreTracker.date >= start_date, DailyStoreTracker.date <= end_date)
        .order_by(DailyStoreTracker.date.desc())
    )
    from .social import tracker_row_dict
    return [tracker_row_dict(r) for r in result.scalars().all()]


async def _get_tracker_months(db: AsyncSession) -> list[str]:
    """Months ("YYYY-MM") that have Daily Input rows, newest first — lets the
    Social Performance page open on the latest month with data rather than
    the current (often still empty) one."""
    result = await db.execute(select(DailyStoreTracker.date).distinct())
    months = {d[:7] for (d,) in result.all() if d and re.match(r"^\d{4}-\d{2}-\d{2}$", d)}
    return sorted(months, reverse=True)


async def _get_store_dashboard_snap(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(StoreDashboardSnapshot).order_by(StoreDashboardSnapshot.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        {
            "store": r.store_name,
            "country": r.country,
            "mtd_revenue": float(r.mtd_revenue or 0),
            "monthly_target": float(r.monthly_target or 0),
            "target_pct": r.target_pct,
            "care_plus_pct": r.care_plus_pct,
            "total_views": r.total_views,
            "engagements": r.engagements,
            "eng_rate_pct": r.eng_rate_pct,
            "prebookings": r.prebookings,
            "dms_received": r.dms_received,
            "wa_response_pct": r.wa_response_pct,
            "walkins_booked": r.walkins_booked,
            "insta_followers": r.insta_followers,
            "follower_growth": r.follower_growth,
            "google_rating": r.google_rating,
            "new_reviews": r.new_reviews,
            "sales_status": r.sales_status,
            "marketing_status": r.marketing_status,
        }
        for r in rows
    ]
