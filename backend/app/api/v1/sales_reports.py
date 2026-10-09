from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select

from ...core.deps import get_current_user, get_db
from ...core.store_scope import allowed_store_ids
from ...models.models import Store, User
from ...services.sales_report_service import (
    get_country_comparison_for_stores, get_country_comparison_snapshot, get_live_today_revenue, get_sales_report,
)

router = APIRouter(prefix="/sales-reports", tags=["sales-reports"])


@router.get("")
async def sales_report(
    granularity: str = "month",
    start: str = None,
    end: str = None,
    team_leader_id: int = None,
    store_id: int = None,
    country: str = None,
    region: str = None,
    group_by: str = "none",
    currency: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unified sales report combining MCP (all countries, authoritative for
    revenue/target) with Sheets-sourced funnel metrics (India only), bucketed
    by day/week/month and optionally grouped by team leader, branch, or region.
    """
    return await get_sales_report(
        db, granularity=granularity, start=start, end=end,
        team_leader_id=team_leader_id, store_id=store_id,
        country=country, region=region, group_by=group_by,
        # only the stores this person is responsible for (all, for company roles)
        store_ids=await allowed_store_ids(user, db),
        # country=All (every country together) only makes sense in one currency
        convert_to_inr=(currency or "").upper() == "INR" or country == "All",
    )


@router.get("/live-today")
async def live_today(
    country: str = "India",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Today's revenue for a country, from the stored mcp_daily_sales table
    (kept fresh by the regular background sync) rather than calling MCP
    directly on every dashboard load."""
    return await get_live_today_revenue(db, country, await allowed_store_ids(user, db))


@router.get("/country-comparison")
async def country_comparison(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Per-country sales normalized to USD, as captured during the last
    sync (see sync_mcp_sales) rather than calling MCP directly. People who
    see only some stores get today's figures for those stores alone."""
    store_ids = await allowed_store_ids(user, db)
    if store_ids is None:
        return await get_country_comparison_snapshot(db)
    today = date.today()
    return await get_country_comparison_for_stores(db, store_ids, today, today)


@router.get("/team-leader/{tl_id}/performance")
async def team_leader_performance_report(
    tl_id: int,
    month: str = None,   # YYYY-MM, default current month
    as_of: str = None,   # YYYY-MM-DD within that month, default today / month end
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One team leader's month against the weekly target plan (35/25/25/15).
    Company roles see anyone; others only a team leader all of whose stores
    they can see (a team leader always sees themselves)."""
    from datetime import date as _date
    from fastapi import HTTPException
    from ...services.tl_performance import team_leader_performance
    today = _date.today()
    try:
        y, m = (int(x) for x in month.split("-")) if month else (today.year, today.month)
        as_of_d = _date.fromisoformat(as_of) if as_of else None
        _date(y, m, 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM and as_of YYYY-MM-DD")
    allowed = await allowed_store_ids(user, db)
    if allowed is not None and tl_id != user.id:
        tl_stores = set((await db.execute(
            select(Store.id).where(Store.team_leader_id == tl_id, Store.is_active == True)  # noqa: E712
        )).scalars().all())
        if not tl_stores or not tl_stores <= set(allowed):
            raise HTTPException(status_code=403, detail="No access to this team leader")
    data = await team_leader_performance(db, tl_id, y, m, as_of_d)
    if data is None:
        raise HTTPException(status_code=404, detail="Team leader not found")
    return data
