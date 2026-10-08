"""Dashboard "All countries": each store's sales are converted to ₹ before
they're added up. Rates: admin (Settings → Currency) > MCP's own conversion
at the last sync > reference.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
from datetime import date

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.models.models import (  # noqa: E402
    CountrySalesSnapshot, Currency, ExchangeRate, McpDailySale, Role, Store, StoreMcpAlias, User,
)
from app.services import sales_report_service as svc  # noqa: E402

DAY = date(2025, 9, 10)


@pytest_asyncio.fixture
async def db(monkeypatch):
    async def _no_backfill(*_a, **_k):
        return None
    monkeypatch.setattr(svc, "_ensure_mcp_coverage", _no_backfill)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        role = Role(name="Team Leader")
        s.add(role)
        await s.flush()
        tl = User(name="T", email="t@x", password_hash="x", role_id=role.id)
        s.add(tl)
        await s.flush()
        india = Store(name="Kochi", team_leader_id=tl.id, country="India", monthly_target=300_000)
        dubai = Store(name="Dubai Mall", team_leader_id=tl.id, country="UAE", monthly_target=30_000)
        s.add_all([india, dubai])
        await s.flush()
        s.add_all([StoreMcpAlias(store_id=india.id, mcp_shop_name="Kochi"),
                   StoreMcpAlias(store_id=dubai.id, mcp_shop_name="Dubai Mall"),
                   McpDailySale(store_id=india.id, date=DAY, revenue=10_000),
                   McpDailySale(store_id=dubai.id, date=DAY, revenue=1_000),
                   # MCP: ₹100,000 = $1,000 and AED 10,000 = $2,700 → 1 AED = ₹27
                   CountrySalesSnapshot(country="INDIA", local_amount=100_000, local_currency="INR", usd_amount=1_000),
                   CountrySalesSnapshot(country="UAE", local_amount=10_000, local_currency="AED", usd_amount=2_700)])
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_rates_prefer_settings_then_mcp_then_reference(db):
    rates = await svc.inr_rates(db)
    assert rates["AED"] == {"rate": pytest.approx(27.0), "source": "mcp"}
    assert rates["BHD"]["source"] == "reference"
    assert rates["BHD"]["rate"] == pytest.approx(2.6596 / 0.01)  # $ per BHD over $ per ₹
    db.add_all([Currency(code="AED", name="Dirham", symbol="AED"),
                ExchangeRate(currency_code="AED", rate_to_base=25.5, effective_date=date(2025, 9, 1))])
    await db.commit()
    assert (await svc.inr_rates(db))["AED"] == {"rate": 25.5, "source": "settings"}


@pytest.mark.asyncio
async def test_all_countries_report_is_in_rupees(db):
    r = await svc.get_sales_report(db, granularity="day", start="2025-09-10", end="2025-09-10",
                                   country="All", group_by="branch", convert_to_inr=True)
    assert r["currency"] == "INR"
    assert r["total_revenue"] == pytest.approx(10_000 + 1_000 * 27)
    assert r["total_target"] == pytest.approx(300_000 + 30_000 * 27)
    by = {g["key"]: g for g in r["breakdown"]}
    assert by["Dubai Mall"]["revenue"] == pytest.approx(27_000)
    assert by["Dubai Mall"]["achievement_pct"] == pytest.approx(3.3, abs=0.1)  # same % as in AED
    assert r["rates"]["AED"]["source"] == "mcp"


@pytest.mark.asyncio
async def test_single_country_stays_in_its_own_currency(db):
    r = await svc.get_sales_report(db, granularity="day", start="2025-09-10", end="2025-09-10", country="UAE")
    assert r["total_revenue"] == 1_000 and r["currency"] == "AED" and r["rates"] is None
