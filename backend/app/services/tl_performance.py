"""Team leader sales performance for one month, measured against a weekly
target plan (W1 days 1–7, W2 8–14, W3 15–21, W4 22–end) instead of an even
daily split.

Numbers returned (all for the team leader's stores, India, INR):
  * monthly achievement   = sales to date / monthly target
  * target till today     = plan of finished weeks + the current week's plan
                            pro-rated by days elapsed in that week
  * ahead / behind plan   = sales to date − target till today
  * projected month-end   = monthly target × (sales to date / target till today)
  * today                 = sales on the as-of day vs that day's plan
  * this week             = sales in the current week vs the week's plan
  * per week / per store / per day breakdowns of the same figures
Sales come from mcp_daily_sales (kept fresh by the MCP sync); the current
month's target from Store.monthly_target (MCP target sheet), past months from
the target stored with that month's daily rows.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import McpDailySale, Store, StoreMcpAlias, User

# Share of the monthly target planned for each week (must add up to 1.0).
WEEK_WEIGHTS = [0.35, 0.25, 0.25, 0.15]
WEEK_STARTS = [1, 8, 15, 22]


def week_ranges(year: int, month: int) -> list[tuple[date, date]]:
    last = calendar.monthrange(year, month)[1]
    out = []
    for i, start_day in enumerate(WEEK_STARTS):
        end_day = WEEK_STARTS[i + 1] - 1 if i + 1 < len(WEEK_STARTS) else last
        out.append((date(year, month, start_day), date(year, month, end_day)))
    return out


def plan_for_day(target: float, d: date) -> float:
    """That calendar day's share of the monthly target."""
    for (ws, we), w in zip(week_ranges(d.year, d.month), WEEK_WEIGHTS):
        if ws <= d <= we:
            return target * w / ((we - ws).days + 1)
    return 0.0


def plan_till(target: float, as_of: date) -> float:
    """Planned sales from the 1st up to and including as_of."""
    total = 0.0
    for (ws, we), w in zip(week_ranges(as_of.year, as_of.month), WEEK_WEIGHTS):
        if as_of >= we:
            total += target * w
        elif as_of >= ws:
            days = (as_of - ws).days + 1
            total += target * w * days / ((we - ws).days + 1)
    return total


def _pct(a: float, b: float) -> float | None:
    return round(a / b * 100, 1) if b else None


def summarise(target: float, daily: dict[date, float], year: int, month: int, as_of: date) -> dict:
    """All headline figures for one target + its daily sales."""
    sales_to_date = sum(v for d, v in daily.items() if d <= as_of)
    till_today = plan_till(target, as_of)
    pace = sales_to_date / till_today if till_today else None
    weeks = []
    current_week = None
    for i, ((ws, we), w) in enumerate(zip(week_ranges(year, month), WEEK_WEIGHTS)):
        days = (we - ws).days + 1
        wk_target = target * w
        wk_sales = sum(v for d, v in daily.items() if ws <= d <= min(we, as_of))
        state = "done" if as_of > we else "current" if as_of >= ws else "upcoming"
        wk_till = plan_till(target, min(as_of, we)) - plan_till(target, ws - timedelta(days=1)) if state != "upcoming" else 0.0
        row = {
            "week": i + 1, "start": ws.isoformat(), "end": we.isoformat(), "days": days,
            "weight_pct": round(w * 100), "target": round(wk_target), "per_day": round(wk_target / days),
            "sales": round(wk_sales), "state": state,
            "achievement_pct": _pct(wk_sales, wk_target),
            "target_till_today": round(wk_till),
            "vs_plan_pct": _pct(wk_sales, wk_till) if state != "upcoming" else None,
        }
        weeks.append(row)
        if state == "current":
            current_week = row
    today_sales = daily.get(as_of, 0.0)
    today_plan = plan_for_day(target, as_of)
    return {
        "target": round(target),
        "sales_to_date": round(sales_to_date),
        "achievement_pct": _pct(sales_to_date, target),
        "target_till_today": round(till_today),
        "target_till_today_pct": _pct(till_today, target),
        "ahead_of_plan": round(sales_to_date - till_today),
        "projected_sales": round(target * pace) if pace is not None and target else None,
        "projected_pct": round(pace * 100, 1) if pace is not None else None,
        "today": {
            "date": as_of.isoformat(), "sales": round(today_sales), "target": round(today_plan),
            "achievement_pct": _pct(today_sales, today_plan),
            "shortfall": round(max(0.0, today_plan - today_sales)),
        },
        "week": current_week,
        "weeks": weeks,
    }


async def team_leader_performance(db: AsyncSession, tl_id: int, year: int, month: int,
                                  as_of: date | None = None) -> dict | None:
    tl = (await db.execute(select(User).where(User.id == tl_id))).scalar_one_or_none()
    if not tl:
        return None
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    today = date.today()
    as_of = as_of or min(today, last)
    as_of = min(max(as_of, first), last)
    is_current = (year, month) == (today.year, today.month)

    stores = (await db.execute(select(Store).where(
        Store.team_leader_id == tl_id, Store.is_active == True, Store.country == "India",  # noqa: E712
    ).order_by(Store.name))).scalars().all()
    ids = [s.id for s in stores]
    aliased = set((await db.execute(
        select(StoreMcpAlias.store_id).where(StoreMcpAlias.store_id.in_(ids)).distinct()
    )).scalars().all()) if ids else set()

    rows = (await db.execute(select(McpDailySale).where(
        McpDailySale.store_id.in_(ids), McpDailySale.date >= first, McpDailySale.date <= last,
    ))).scalars().all() if ids else []
    by_store: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    row_targets: dict[int, float] = defaultdict(float)
    for r in rows:
        by_store[r.store_id][r.date] += float(r.revenue or 0)
        row_targets[r.store_id] = max(row_targets[r.store_id], float(r.target or 0))

    def store_target(s: Store) -> float:
        if is_current:
            return float(s.monthly_target or 0) if s.id in aliased else 0.0
        return row_targets.get(s.id, 0.0)  # past month: target recorded with that month's sales

    team_daily: dict[date, float] = defaultdict(float)
    store_rows = []
    total_target = 0.0
    for s in stores:
        t = store_target(s)
        total_target += t
        daily = by_store.get(s.id, {})
        for d, v in daily.items():
            team_daily[d] += v
        summ = summarise(t, daily, year, month, as_of)
        store_rows.append({
            "store_id": s.id, "name": s.name, "region": s.region,
            **{k: summ[k] for k in ("target", "sales_to_date", "achievement_pct", "target_till_today",
                                    "ahead_of_plan", "projected_sales", "projected_pct")},
            "today_sales": summ["today"]["sales"], "today_target": summ["today"]["target"],
            "week_sales": summ["week"]["sales"] if summ["week"] else None,
        })

    team = summarise(total_target, team_daily, year, month, as_of)
    days = []
    d = first
    while d <= last:
        days.append({
            "date": d.isoformat(), "plan": round(plan_for_day(total_target, d)),
            "sales": round(team_daily.get(d, 0.0)) if d <= as_of else None,
        })
        d += timedelta(days=1)

    # Same day last month, for a like-for-like comparison.
    prev_last_day = first - timedelta(days=1)
    prev_first = prev_last_day.replace(day=1)
    prev_as_of = prev_first.replace(day=min(as_of.day, prev_last_day.day))
    prev_sales = float((await db.execute(select(func.coalesce(func.sum(McpDailySale.revenue), 0)).where(
        McpDailySale.store_id.in_(ids), McpDailySale.date >= prev_first, McpDailySale.date <= prev_as_of,
    ))).scalar() or 0) if ids else 0.0

    last_synced = (await db.execute(select(func.max(McpDailySale.synced_at)).where(
        McpDailySale.store_id.in_(ids)))).scalar() if ids else None
    return {
        "team_leader": {"id": tl.id, "name": tl.name},
        "month": f"{year:04d}-{month:02d}", "as_of": as_of.isoformat(), "is_current_month": is_current,
        "week_plan": [{"week": i + 1, "weight_pct": round(w * 100)} for i, w in enumerate(WEEK_WEIGHTS)],
        "stores": store_rows, "store_count": len(stores),
        **team,
        "days": days,
        "last_month_same_period": {
            "until": prev_as_of.isoformat(), "sales": round(prev_sales),
            "change_pct": _pct(team["sales_to_date"] - prev_sales, prev_sales),
        },
        "last_synced_at": last_synced.isoformat() if last_synced else None,
    }
