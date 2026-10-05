from datetime import date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..models.models import Store, User, McpDailySale, DailySubmission, CountrySalesSnapshot, StoreMcpAlias
from .mcp_sync_service import sync_mcp_sales


async def get_live_today_revenue(db: AsyncSession, country: str) -> dict:
    """Today's revenue for a country, read from the stored mcp_daily_sales
    table (kept fresh by the same background sync every report page
    already triggers) instead of calling MCP directly. Deliberately sums
    EVERY store tagged with this country regardless of needs_review status
    — this is meant to be a raw, unfiltered pulse independent of branch
    confirmation state, same as it was when it called MCP live."""
    today = date.today()
    total = (await db.execute(
        select(func.coalesce(func.sum(McpDailySale.revenue), 0))
        .select_from(McpDailySale)
        .join(Store, Store.id == McpDailySale.store_id)
        .where(Store.country == country, McpDailySale.date == today)
    )).scalar()
    return {"country": country, "date": today.isoformat(), "revenue": float(total or 0)}


async def get_country_comparison_snapshot(db: AsyncSession) -> list[dict]:
    """Reads the country-comparison totals saved during the last sync
    (see mcp_sync_service.sync_mcp_sales) instead of calling MCP directly —
    MCP already does its own USD conversion at sync time, so this just
    returns what was last recorded."""
    rows = (await db.execute(select(CountrySalesSnapshot))).scalars().all()
    return [
        {
            "country": r.country,
            "local_amount": float(r.local_amount or 0),
            "local_currency": r.local_currency or "",
            "usd_amount": float(r.usd_amount or 0),
            "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        }
        for r in rows
    ]


def _default_range(granularity: str) -> tuple[date, date]:
    today = date.today()
    if granularity == "day":
        return today, today
    if granularity == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    # month
    start = today.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    return start, next_month - timedelta(days=1)


def _bucket_key(d: date, granularity: str) -> str:
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat()
    return d.strftime("%Y-%m")


async def _ensure_mcp_coverage(db: AsyncSession, start_date: date, end_date: date) -> None:
    """Lazily backfill mcp_daily_sales for the requested range if it isn't
    fully synced yet, so filtering by an arbitrary date range doesn't just
    return an empty/partial result.

    Today is a special case: it's never "fully synced" in the sense the
    other dates are — new sales keep landing in MCP as the day goes on, so
    a row already existing for today doesn't mean today is complete. Always
    re-pull just today's date (a single day, cheap) whenever it's in range,
    instead of only backfilling when a date is entirely missing.
    """
    today = date.today()
    result = await db.execute(
        select(McpDailySale.date).where(
            McpDailySale.date >= start_date, McpDailySale.date <= end_date
        ).distinct()
    )
    synced_dates = {row[0] for row in result.all()}
    expected_days = (end_date - start_date).days + 1
    fully_covered = len(synced_dates) >= expected_days
    includes_today = start_date <= today <= end_date

    if not fully_covered:
        await sync_mcp_sales(db, start_date.isoformat(), end_date.isoformat())
    elif includes_today:
        await sync_mcp_sales(db, today.isoformat(), today.isoformat())


async def get_sales_report(
    db: AsyncSession,
    granularity: str = "month",
    start: Optional[str] = None,
    end: Optional[str] = None,
    team_leader_id: Optional[int] = None,
    store_id: Optional[int] = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    group_by: str = "none",
    store_ids: Optional[list[int]] = None,
) -> dict:
    if granularity not in ("day", "week", "month"):
        granularity = "month"
    if start and end:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    else:
        start_date, end_date = _default_range(granularity)

    await _ensure_mcp_coverage(db, start_date, end_date)

    store_q = select(Store, User.name.label("tl_name")).outerjoin(
        User, Store.team_leader_id == User.id
    ).where(Store.is_active == True)
    if team_leader_id is not None:
        store_q = store_q.where(Store.team_leader_id == team_leader_id)
    if store_id is not None:
        store_q = store_q.where(Store.id == store_id)
    if store_ids is not None:
        store_q = store_q.where(Store.id.in_(store_ids or [-1]))
    if country:
        store_q = store_q.where(Store.country == country)
    if region:
        store_q = store_q.where(Store.region == region)

    store_rows = (await db.execute(store_q)).all()
    stores_by_id = {s.id: (s, tl_name) for s, tl_name in store_rows}
    store_ids = list(stores_by_id.keys())
    if not store_ids:
        return {
            "start": start_date.isoformat(), "end": end_date.isoformat(), "granularity": granularity,
            "total_revenue": 0, "total_target": 0, "achievement_pct": 0,
            "total_walkins": 0, "total_conversions": 0,
            "trend": [], "breakdown": [], "needs_review": [], "top_branch": None,
        }

    india_store_ids = [sid for sid, (s, _) in stores_by_id.items() if s.country == "India"]

    sales_rows = (await db.execute(
        select(McpDailySale).where(
            McpDailySale.store_id.in_(store_ids),
            McpDailySale.date >= start_date,
            McpDailySale.date <= end_date,
        )
    )).scalars().all()

    # Target comes from Store.monthly_target — kept current every sync from
    # MCP's live current-month target sheet (see
    # mcp_sync_service.sync_mcp_sales) independent of transaction activity —
    # but ONLY for stores MCP actually maintains a target for. A store with
    # no recorded MCP alias at all has never been confirmed as an active
    # branch by that sync; its monthly_target field is often just a stale,
    # manually-entered number from initial setup (frequently on old
    # duplicate branches that a real branch has since replaced), and
    # including it here silently double-counts against the real branch's
    # already-correct MCP-driven target.
    aliased_store_ids = {row[0] for row in (await db.execute(
        select(StoreMcpAlias.store_id).where(StoreMcpAlias.store_id.in_(store_ids)).distinct()
    )).all()}

    funnel_rows = []
    if india_store_ids:
        funnel_rows = (await db.execute(
            select(DailySubmission).where(
                DailySubmission.store_id.in_(india_store_ids),
                DailySubmission.date >= start_date,
                DailySubmission.date <= end_date,
            )
        )).scalars().all()

    # Store.monthly_target is a single month's figure. For a range that
    # genuinely spans multiple months (6 Month, 1 Year, or a wide custom
    # range), comparing many months of revenue against only one month's
    # target understates target and makes Achievement % look inflated.
    # Scale by how many months the selected range actually represents —
    # e.g. ~30 days -> 1x (the "Month" preset, unchanged from before),
    # ~183 days -> 6x, ~365 days -> 12x — rather than trying to look up
    # each individual past month's own target (which would be incomplete
    # for any month a branch didn't happen to sync in, or didn't exist
    # yet), this keeps the scaling predictable and matches how these
    # period presets are meant to be read: "6 months' worth of target."
    days_in_range = (end_date - start_date).days + 1
    month_multiplier = max(1, round(days_in_range / 30.44))

    # Per-store aggregates: revenue sums across days in the selected range;
    # target comes straight from the Store record (scaled per above), but
    # only when MCP actively maintains it (see note above).
    per_store: dict[int, dict] = {}
    for sid in store_ids:
        store_target = float(stores_by_id[sid][0].monthly_target or 0) if sid in aliased_store_ids else 0.0
        per_store[sid] = {"revenue": 0.0, "target": store_target * month_multiplier, "walkins": 0, "conversions": 0, "units_sold": 0}

    trend_map: dict[str, dict] = {}
    for row in sales_rows:
        agg = per_store[row.store_id]
        agg["revenue"] += float(row.revenue or 0)
        agg["units_sold"] += row.units_sold or 0

        key = _bucket_key(row.date, granularity)
        bucket = trend_map.setdefault(key, {"period": key, "revenue": 0.0})
        bucket["revenue"] += float(row.revenue or 0)

    for row in funnel_rows:
        agg = per_store[row.store_id]
        agg["walkins"] += row.walk_ins or 0
        agg["conversions"] += row.walk_in_conversions or 0

    confirmed_ids = [sid for sid, (s, _) in stores_by_id.items() if not s.needs_review]
    review_ids = [sid for sid, (s, _) in stores_by_id.items() if s.needs_review]

    total_revenue = sum(per_store[sid]["revenue"] for sid in confirmed_ids)
    total_target = sum(per_store[sid]["target"] for sid in confirmed_ids)
    total_walkins = sum(per_store[sid]["walkins"] for sid in confirmed_ids)
    total_conversions = sum(per_store[sid]["conversions"] for sid in confirmed_ids)
    total_units_sold = sum(per_store[sid]["units_sold"] for sid in confirmed_ids)

    def _group_key(sid: int) -> str:
        store, tl_name = stores_by_id[sid]
        if group_by == "team_leader":
            return tl_name or "Unassigned"
        if group_by == "branch":
            return store.name
        if group_by == "region":
            return store.region or store.country or "Unknown"
        return "All"

    group_map: dict[str, dict] = {}
    for sid in confirmed_ids:
        key = _group_key(sid)
        store, _ = stores_by_id[sid]
        # Each branch/region group is within one country, so its own currency
        # can be shown correctly instead of defaulting to INR everywhere.
        g = group_map.setdefault(key, {
            "key": key, "country": store.country, "revenue": 0.0, "target": 0.0,
            "walkins": 0, "conversions": 0, "units_sold": 0, "store_count": 0, "stores": [],
        })
        g["revenue"] += per_store[sid]["revenue"]
        g["target"] += per_store[sid]["target"]
        g["walkins"] += per_store[sid]["walkins"]
        g["conversions"] += per_store[sid]["conversions"]
        g["units_sold"] += per_store[sid]["units_sold"]
        g["store_count"] += 1
        g["stores"].append(store.name)

    breakdown = []
    for g in group_map.values():
        g["achievement_pct"] = round(g["revenue"] / g["target"] * 100, 1) if g["target"] > 0 else 0
        breakdown.append(g)
    breakdown.sort(key=lambda x: x["revenue"], reverse=True)

    # Top branch by revenue for this exact period — computed by branch name
    # regardless of the requested group_by, so "who's #1 right now" is always
    # available even when viewing the team-leader/region/all-together rollup.
    branch_totals: dict[str, dict] = {}
    for sid in confirmed_ids:
        store, _ = stores_by_id[sid]
        b = branch_totals.setdefault(store.name, {"name": store.name, "country": store.country, "revenue": 0.0, "target": 0.0})
        b["revenue"] += per_store[sid]["revenue"]
        b["target"] += per_store[sid]["target"]
    top_branch = None
    if branch_totals:
        top_branch = max(branch_totals.values(), key=lambda x: x["revenue"])
        top_branch["achievement_pct"] = (
            round(top_branch["revenue"] / top_branch["target"] * 100, 1) if top_branch["target"] > 0 else 0
        )

    needs_review = []
    for sid in review_ids:
        store, _ = stores_by_id[sid]
        needs_review.append({
            "store_id": sid, "store": store.name, "country": store.country,
            "revenue": per_store[sid]["revenue"],
        })

    trend = sorted(trend_map.values(), key=lambda x: x["period"])

    return {
        "start": start_date.isoformat(), "end": end_date.isoformat(), "granularity": granularity,
        "total_revenue": total_revenue, "total_target": total_target,
        "achievement_pct": round(total_revenue / total_target * 100, 1) if total_target > 0 else 0,
        "total_walkins": total_walkins, "total_conversions": total_conversions,
        "total_units_sold": total_units_sold,
        "trend": trend, "breakdown": breakdown, "needs_review": needs_review,
        "top_branch": top_branch,
    }
