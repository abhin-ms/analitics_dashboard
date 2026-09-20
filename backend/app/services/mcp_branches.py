import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from .smart_service_client import smart_service
from .mcp_parsers import parse_shop_stock_position, parse_shop_target_achievement

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300  # 5 minutes

MCP_COUNTRIES = [
    {"id": 1, "name": "India"},
    {"id": 2, "name": "Oman"},
    {"id": 3, "name": "Pakistan"},
    {"id": 4, "name": "UAE"},
    {"id": 5, "name": "Malaysia"},
    {"id": 6, "name": "UK"},
    {"id": 7, "name": "Bahrain"},
    {"id": 8, "name": "Qatar"},
]

# get_all_branches() below sources India from the local DB (synced from
# Google Sheets) instead of MCP, since that's still the only source for
# walk-ins/leads/calls funnel metrics. Everything else that wants MCP data
# for every country (e.g. the sales sync service) should use MCP_COUNTRIES
# directly, which includes India.
_NON_INDIA_MCP_COUNTRIES = [c for c in MCP_COUNTRIES if c["id"] != 1]


def _now():
    import time
    return time.time()


def _get_cached(key: str) -> Optional[Any]:
    if key in _cache:
        ts, data = _cache[key]
        if _now() - ts < _CACHE_TTL:
            return data
        del _cache[key]
    return None


def _set_cached(key: str, data: Any):
    _cache[key] = (_now(), data)


def _normalize_shop(name: str) -> str:
    return name.strip().lower().replace("  ", " ")


def _loose_key(name: str) -> str:
    """Matches an MCP shop name to a stored alias despite the small spelling
    differences MCP has between endpoints (e.g. 'Solution -Guwahati' vs
    'Solution - Guwahati')."""
    return re.sub(r"\s+", " ", re.sub(r"\s*-\s*", " - ", name.strip().lower()))


def _month_multiplier(start: date, end: date) -> int:
    """Same rule sales_report_service uses: a target is one month's figure,
    so a multi-month range compares against that many months of target."""
    return max(1, round(((end - start).days + 1) / 30.44))


async def _get_india_branches_from_db(
    db: AsyncSession, india_stock: dict[str, dict], start: date, end: date
) -> list[dict[str, Any]]:
    """India branches for the dashboard's "All Branches" list — everything
    shown comes from MCP.

    Which branches appear: confirmed, active stores with at least one MCP
    alias (the same rule the target totals use), so Sheets-created
    placeholders/duplicates never show. Revenue and units come from MCP's
    sales (McpDailySale, calendar month to date), the target from MCP's
    target sheet (kept on the store by the sync), and stock from MCP's
    stock position, matched to the store through its recorded MCP names.
    The team leader name is our own assignment. No Google Sheets data is
    used here.
    """
    from ..models.models import Store, User, McpDailySale, StoreMcpAlias

    multiplier = _month_multiplier(start, end)

    aliased_ids = select(StoreMcpAlias.store_id).distinct()
    rows = (await db.execute(
        select(Store, User.name)
        .outerjoin(User, Store.team_leader_id == User.id)
        .where(
            Store.is_active == True, Store.country == "India",
            Store.needs_review == False, Store.id.in_(aliased_ids),
        )
    )).all()

    alias_rows = (await db.execute(select(StoreMcpAlias.store_id, StoreMcpAlias.mcp_shop_name))).all()
    aliases_by_store: dict[int, list[str]] = {}
    for sid, alias_name in alias_rows:
        aliases_by_store.setdefault(sid, []).append(alias_name)

    mcp_rows = (await db.execute(
        select(
            McpDailySale.store_id,
            func.coalesce(func.sum(McpDailySale.revenue), 0),
            func.coalesce(func.sum(McpDailySale.units_sold), 0),
        ).where(McpDailySale.date >= start, McpDailySale.date <= end).group_by(McpDailySale.store_id)
    )).all()
    mcp_by_store = {r[0]: (float(r[1] or 0), int(r[2] or 0)) for r in mcp_rows}

    branches = []
    for store, tl_name in rows:
        revenue, units = mcp_by_store.get(store.id, (0.0, 0))
        target = float(store.monthly_target or 0) * multiplier
        achievement_pct = (revenue / target * 100) if target > 0 else 0

        stock_units, stock_items = 0, []
        for alias_name in aliases_by_store.get(store.id, []):
            st = india_stock.get(_loose_key(alias_name))
            if st:
                stock_units += st.get("stock_units", 0)
                stock_items += st.get("stock_items", [])

        branches.append({
            "shop": store.name,
            "country": "India",
            "country_id": 1,
            "target": target,
            "actual": revenue,
            "achievement_pct": round(achievement_pct, 1),
            "status": "",
            "stock_units": stock_units,
            "stock_items": stock_items,
            "units_sold": units,
            "tl": tl_name or "Unassigned",
        })

    return branches


async def _fill_non_india_revenue(
    db: AsyncSession, branches: list[dict[str, Any]], start: date, end: date, is_default_range: bool
) -> None:
    """MCP's target sheet has no rows for most non-India shops and only
    covers the current month, so revenue for any selected period comes
    from the sales the sync already stores per shop (matched through each
    store's recorded MCP names). A shop we can't match to a stored store
    keeps MCP's own current-month figure, and only for the default range."""
    from ..models.models import Store, McpDailySale, StoreMcpAlias

    known = {
        _loose_key(n) for (n,) in (await db.execute(
            select(StoreMcpAlias.mcp_shop_name).join(Store, Store.id == StoreMcpAlias.store_id)
            .where(Store.country != "India")
        )).all()
    }
    revenue_rows = (await db.execute(
        select(StoreMcpAlias.mcp_shop_name, func.coalesce(func.sum(McpDailySale.revenue), 0))
        .join(Store, Store.id == StoreMcpAlias.store_id)
        .join(McpDailySale, McpDailySale.store_id == Store.id)
        .where(Store.country != "India", McpDailySale.date >= start, McpDailySale.date <= end)
        .group_by(StoreMcpAlias.mcp_shop_name)
    )).all()
    revenue_by_name = {_loose_key(name): float(rev or 0) for name, rev in revenue_rows}
    multiplier = _month_multiplier(start, end)
    for b in branches:
        key = _loose_key(b["shop"])
        if key in known:
            b["actual"] = revenue_by_name.get(key, 0.0)
        elif not is_default_range:
            b["actual"] = 0.0
        b["target"] = (b.get("target") or 0) * multiplier
        b["achievement_pct"] = round(b["actual"] / b["target"] * 100, 1) if b["target"] > 0 else 0


async def get_all_branches(
    db: AsyncSession, start: Optional[date] = None, end: Optional[date] = None
) -> list[dict[str, Any]]:
    """Extract all branches from combined sources:
    - India: confirmed, MCP-managed stores; all figures from MCP
    - Other countries: MCP (SmartService live API)

    Returns list of: {
        shop, country, country_id, target, actual, achievement_pct,
        stock_units, stock_items
    }
    """
    today = date.today()
    is_default_range = start is None and end is None
    start = start or today.replace(day=1)
    end = end or today
    if not is_default_range:
        # A wide range (6 Month / 1 Year / Custom) may cover days the sync
        # hasn't stored yet — backfill them the same way /sales-reports does.
        from .sales_report_service import _ensure_mcp_coverage
        await _ensure_mcp_coverage(db, start, end)

    cache_key = f"all_branches:{start}:{end}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    async def fetch_india_stock() -> dict[str, dict]:
        try:
            raw = await smart_service.shop_stock_position(country_id=1)
            return {
                _loose_key(x["shop"]): {"stock_units": x.get("total_units", 0), "stock_items": x.get("items", [])}
                for x in parse_shop_stock_position(raw)
            }
        except Exception as e:
            logger.warning("Failed to fetch India stock: %s", e)
            return {}

    async def build_india():
        return await _get_india_branches_from_db(db, await fetch_india_stock(), start, end)

    india_task = build_india()

    async def fetch_mcp_branches():
        # 1. Get stock position per country (concurrently)
        async def fetch_country_stock(country_id: int) -> list[dict]:
            try:
                raw = await smart_service.shop_stock_position(country_id=country_id)
                return parse_shop_stock_position(raw)
            except Exception as e:
                logger.warning("Failed to fetch stock for country %d: %s", country_id, e)
                return []

        # 2. Get target achievement per non-India country (concurrently)
        async def fetch_country_targets(country_id: int) -> list[dict]:
            try:
                now = datetime.now()
                raw = await smart_service.shop_target_achievement(
                    country_id=country_id,
                    year=now.year,
                    month=now.strftime("%B"),
                )
                return parse_shop_target_achievement(raw)
            except Exception as e:
                logger.warning("Failed to fetch targets for country %d: %s", country_id, e)
                return []

        # Run stock + target fetches per country concurrently (India excluded —
        # it's sourced from the local DB via india_task above)
        stock_results, target_results = await asyncio.gather(
            asyncio.gather(*[fetch_country_stock(c["id"]) for c in _NON_INDIA_MCP_COUNTRIES]),
            asyncio.gather(*[fetch_country_targets(c["id"]) for c in _NON_INDIA_MCP_COUNTRIES]),
        )

        # Merge stock data per country
        stock_by_shop: dict[str, dict] = {}
        for country_idx, country_shops in enumerate(stock_results):
            country = _NON_INDIA_MCP_COUNTRIES[country_idx]
            for s in country_shops:
                key = _normalize_shop(s["shop"])
                # Keep the shop's real name and the country it was fetched
                # under — this used to be dropped, so any shop with stock
                # but no target row this month was listed as country
                # "Unknown" (and shown in lowercase) even though the
                # country was already known at fetch time.
                stock_by_shop[key] = {
                    "shop": s["shop"],
                    "country": country["name"],
                    "country_id": country["id"],
                    "stock_units": s.get("total_units", 0),
                    "stock_items": s.get("items", []),
                }

        # 3. Build branch list from MCP target data
        branches: dict[str, dict] = {}
        for country_idx, shops in enumerate(target_results):
            country = _NON_INDIA_MCP_COUNTRIES[country_idx]
            for s in shops:
                shop_name = s.get("shop", "")
                if not shop_name:
                    continue
                key = _normalize_shop(shop_name)
                stock = stock_by_shop.get(key, {})
                branches[key] = {
                    "shop": shop_name,
                    "country": country["name"],
                    "country_id": country["id"],
                    "target": s.get("target", 0),
                    "actual": s.get("actual", 0),
                    "achievement_pct": s.get("achievement_pct", 0),
                    "status": s.get("status", ""),
                    "stock_units": stock.get("stock_units", 0),
                    "stock_items": stock.get("stock_items", []),
                }

        # 4. Add stock-only shops not found in target data
        for key, stock in stock_by_shop.items():
            if key not in branches:
                branches[key] = {
                    "shop": stock.get("shop", key),
                    "country": stock.get("country", "Unknown"),
                    "country_id": stock.get("country_id", 0),
                    "target": 0,
                    "actual": 0,
                    "achievement_pct": 0,
                    "status": "",
                    "stock_units": stock.get("stock_units", 0),
                    "stock_items": stock.get("stock_items", []),
                }

        return list(branches.values())

    mcp_task = fetch_mcp_branches()

    india_branches, mcp_branches = await asyncio.gather(india_task, mcp_task)
    # After the gather, not inside it: one DB session can't run two queries at once.
    await _fill_non_india_revenue(db, mcp_branches, start, end, is_default_range)

    # Merge: India from DB + others from MCP
    all_branches = india_branches + mcp_branches
    result = sorted(all_branches, key=lambda x: (x["country"], x["shop"]))
    _set_cached(cache_key, result)
    return result
