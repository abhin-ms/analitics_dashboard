import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, require_admin_tier
from ...models.models import User
from ...services.mcp_daily_sales import (
    get_daily_sales,
    get_sales_summary,
    get_country_comparison,
    get_top_models,
    get_shop_wise_sales,
)
from ...services.mcp_stock import (
    get_stock_position,
    get_stock_summary,
    get_pending_items,
)
from ...services.mcp_branches import get_all_branches
from ...services.smart_service_client import smart_service
from ...services.mcp_parsers import (
    parse_daybook_summary,
    parse_cashbook_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp-reports"])


# ── Response Models ──────────────────────────────────────────────────


class DailySalesRow(BaseModel):
    date: str
    store: str
    revenue: float
    units_sold: int
    new_sale_count: int = 0
    replacement_count: int = 0
    return_count: int = 0
    target: float = 0.0
    country_id: int = 0


class SalesSummaryResponse(BaseModel):
    transactions: int = 0
    gross: float = 0.0
    discount: float = 0.0
    net: float = 0.0
    currency: str = ""
    period: str = ""


class CountryComparisonResponse(BaseModel):
    country: str
    local_amount: float
    local_currency: str
    sales_count: int
    usd_amount: float
    pct: float
    avg_ticket_usd: float


class TopModelResponse(BaseModel):
    rank: int
    model: str
    units: int
    amount: float


class ShopWiseSalesResponse(BaseModel):
    shop: str
    total_sales: int
    total_amount: float
    categories: dict = {}
    purchase_types: dict = {}
    payment_methods: dict = {}


class ShopTargetResponse(BaseModel):
    shop: str
    target: float
    actual: float
    achievement_pct: float
    status: str = ""


class StockItemResponse(BaseModel):
    count: int
    model: str
    material: str
    position: str


class StockShopResponse(BaseModel):
    shop: str
    items: list[StockItemResponse]
    total_units: int


class StockSummaryResponse(BaseModel):
    total_units: int
    shop_count: int
    stock_by_shop: list[dict]
    low_stock_items: list[dict]


class PendingShopResponse(BaseModel):
    shop: str
    email: str = ""
    payment_pending: int = 0
    installation_pending: int = 0
    items: list[str] = []


class DaybookDayResponse(BaseModel):
    date: str
    opening: float
    income: float
    expense: float
    closing: float
    is_closed: bool = False


class CashbookResponse(BaseModel):
    opening: float
    income: float
    expense: float
    balance: float
    currency: str = ""


class TransactionResponse(BaseModel):
    id: int
    date: str
    shop: str
    category: str
    model: str
    imei: str
    amount: float
    discount: float
    paid: bool


# ── Sales Endpoints ──────────────────────────────────────────────────


@router.get("/sales/daily", response_model=list[DailySalesRow])
async def mcp_daily_sales(
    country_id: int = Query(..., description="Country ID: 1=India 2=Oman 3=Pakistan 4=UAE 5=Malaysia 6=UK 7=Bahrain 8=Qatar"),
    from_date: str = Query(..., description="Start date YYYY-MM-DD"),
    to_date: str = Query(..., description="End date YYYY-MM-DD"),
    user: User = require_admin_tier(),
):
    """Daily-aggregated sales by store from SmartService MCP."""
    try:
        data = await get_daily_sales(country_id, from_date, to_date)
        return data
    except Exception as e:
        logger.error("MCP daily sales failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/sales/summary", response_model=SalesSummaryResponse)
async def mcp_sales_summary(
    from_date: str = Query(...),
    to_date: str = Query(None),
    country_id: int = Query(None),
    shop_id: int = Query(None),
    user: User = require_admin_tier(),
):
    """Sales summary (total count, gross, discount, net) from SmartService MCP."""
    try:
        return await get_sales_summary(from_date, to_date, country_id, shop_id)
    except Exception as e:
        logger.error("MCP sales summary failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/sales/shop-wise", response_model=list[ShopWiseSalesResponse])
async def mcp_shop_wise_sales(
    country_id: int = Query(...),
    from_date: str = Query(...),
    to_date: str = Query(None),
    user: User = require_admin_tier(),
):
    """Shop-wise sales breakdown for a single country from SmartService MCP."""
    try:
        return await get_shop_wise_sales(country_id, from_date, to_date)
    except Exception as e:
        logger.error("MCP shop-wise sales failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/sales/top-models", response_model=list[TopModelResponse])
async def mcp_top_models(
    country_id: int = Query(...),
    from_date: str = Query(...),
    to_date: str = Query(None),
    top_n: int = Query(10, ge=1, le=50),
    user: User = require_admin_tier(),
):
    """Top-selling models for a country from SmartService MCP."""
    try:
        return await get_top_models(country_id, from_date, to_date, top_n)
    except Exception as e:
        logger.error("MCP top models failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/sales/country-comparison", response_model=list[CountryComparisonResponse])
async def mcp_country_comparison(
    from_date: str = Query(...),
    to_date: str = Query(None),
    user: User = require_admin_tier(),
):
    """Cross-country sales comparison normalized to USD from SmartService MCP."""
    try:
        return await get_country_comparison(from_date, to_date)
    except Exception as e:
        logger.error("MCP country comparison failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/sales/targets", response_model=list[ShopTargetResponse])
async def mcp_shop_targets(
    country_id: int = Query(...),
    year: int = Query(...),
    month: str = Query(..., description="Full month name, e.g. August"),
    shop_id: int = Query(None),
    user: User = require_admin_tier(),
):
    """Per-shop target vs actual achievement from SmartService MCP."""
    try:
        raw = await smart_service.shop_target_achievement(
            country_id=country_id, year=year, month=month, shop_id=shop_id
        )
        from ...services.mcp_parsers import parse_shop_target_achievement
        return parse_shop_target_achievement(raw)
    except Exception as e:
        logger.error("MCP shop targets failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/sales/transactions", response_model=list[TransactionResponse])
async def mcp_transactions(
    from_date: str = Query(...),
    to_date: str = Query(None),
    country_id: int = Query(None),
    shop_id: int = Query(None),
    purchase_category_id: int = Query(None),
    purchase_type_id: int = Query(None),
    model_id: int = Query(None),
    customer_search: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: User = require_admin_tier(),
):
    """Line-level transaction listing from SmartService MCP."""
    try:
        raw = await smart_service.transaction_detail(
            from_date=from_date,
            to_date=to_date,
            country_id=country_id,
            shop_id=shop_id,
            purchase_category_id=purchase_category_id,
            purchase_type_id=purchase_type_id,
            model_id=model_id,
            customer_search=customer_search,
            limit=limit,
        )
        from ...services.mcp_parsers import parse_transaction_detail
        return parse_transaction_detail(raw)
    except Exception as e:
        logger.error("MCP transactions failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


# ── Stock Endpoints ──────────────────────────────────────────────────


@router.get("/stock/position", response_model=list[StockShopResponse])
async def mcp_stock_position(
    country_id: int = Query(None),
    shop_id: int = Query(None),
    low_stock_threshold: int = Query(None),
    user: User = require_admin_tier(),
):
    """Current stock position by shop from SmartService MCP."""
    try:
        return await get_stock_position(country_id, shop_id, low_stock_threshold)
    except Exception as e:
        logger.error("MCP stock position failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/stock/summary", response_model=StockSummaryResponse)
async def mcp_stock_summary(
    country_id: int = Query(None),
    user: User = require_admin_tier(),
):
    """Stock summary with totals and low-stock items from SmartService MCP."""
    try:
        return await get_stock_summary(country_id)
    except Exception as e:
        logger.error("MCP stock summary failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/stock/pending", response_model=list[PendingShopResponse])
async def mcp_pending_items(
    country_id: int = Query(None),
    shop_id: int = Query(None),
    include: str = Query("both", description="payment, installation, or both"),
    user: User = require_admin_tier(),
):
    """Payment and installation pending items by shop from SmartService MCP."""
    try:
        return await get_pending_items(country_id, shop_id, include)
    except Exception as e:
        logger.error("MCP pending items failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


# ── Daybook / Cashbook Endpoints ─────────────────────────────────────


@router.get("/daybook/{shop_id}", response_model=list[DaybookDayResponse])
async def mcp_daybook(
    shop_id: int,
    from_date: str = Query(...),
    to_date: str = Query(None),
    user: User = require_admin_tier(),
):
    """Per-shop daybook summary from SmartService MCP."""
    try:
        raw = await smart_service.daybook_summary(shop_id, from_date, to_date)
        return parse_daybook_summary(raw)
    except Exception as e:
        logger.error("MCP daybook failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


@router.get("/cashbook/{shop_id}", response_model=CashbookResponse)
async def mcp_cashbook(
    shop_id: int,
    user: User = require_admin_tier(),
):
    """Per-shop cash position from SmartService MCP."""
    try:
        raw = await smart_service.cashbook_summary(shop_id)
        return parse_cashbook_summary(raw)
    except Exception as e:
        logger.error("MCP cashbook failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


# ── Health Check ─────────────────────────────────────────────────────


@router.get("/health")
async def mcp_health(user: User = require_admin_tier()):
    """SmartService MCP health check."""
    return await smart_service.health_check()


# ── Branches ────────────────────────────────────────────────────────


class BranchResponse(BaseModel):
    shop: str
    country: str
    country_id: int = 0
    target: float = 0.0
    actual: float = 0.0
    achievement_pct: float = 0.0
    status: str = ""
    stock_units: int = 0
    stock_items: list[dict] = []
    units_sold: int = 0
    walk_ins: int = 0
    conversions: int = 0
    tl: str = ""


@router.get("/branches", response_model=list[BranchResponse])
async def mcp_branches(
    start: str = None,
    end: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_admin_tier(),
):
    """List all branches with country, targets, and stock from MCP + DB.
    start/end (YYYY-MM-DD) scope revenue and target to that period; without
    them it's the current calendar month to date."""
    try:
        from datetime import date as _date
        return await get_all_branches(
            db,
            _date.fromisoformat(start) if start else None,
            _date.fromisoformat(end) if end else None,
        )
    except Exception as e:
        logger.error("MCP branches failed: %s", e)
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")
