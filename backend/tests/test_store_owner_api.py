"""Store Owner dashboard: an owner sees sales, leads and staff for the stores
linked to them and nothing else. In-memory SQLite, auth overridden, the MCP
back-fill switched off.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
from datetime import date, datetime, timedelta

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.deps import get_current_user  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    McpDailySale, Role, Store, StoreStaff, TeleAppointment, TeleCallLead, User, UserStoreAccess,
)
from app.services import sales_report_service  # noqa: E402


@pytest_asyncio.fixture
async def env(monkeypatch):
    async def _no_backfill(*_a, **_k):
        return None
    monkeypatch.setattr(sales_report_service, "_ensure_mcp_coverage", _no_backfill)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        roles = {}
        for name in ("Store Owner", "Team Leader", "Salesperson", "Telecaller"):
            roles[name] = Role(name=name)
            db.add(roles[name])
        await db.flush()
        tl = User(name="Tara Lead", email="tl@x", password_hash="x", role_id=roles["Team Leader"].id)
        db.add(tl)
        await db.flush()
        a = Store(name="Kerala Kochi", team_leader_id=tl.id, country="India")
        b = Store(name="Mysore", team_leader_id=tl.id, country="India")
        c = Store(name="Chennai Velachery", team_leader_id=tl.id, country="India")
        db.add_all([a, b, c])
        await db.flush()
        u = {
            "tl": tl,
            "owner": User(name="Omar Owner", email="o@x", password_hash="x", role_id=roles["Store Owner"].id),
            "sam": User(name="Sam Sales", email="s@x", password_hash="x", role_id=roles["Salesperson"].id, store_id=a.id),
            "tia": User(name="Tia Caller", email="t@x", password_hash="x", role_id=roles["Telecaller"].id, store_id=b.id),
            "other": User(name="Olu Other", email="x@x", password_hash="x", role_id=roles["Salesperson"].id, store_id=c.id),
        }
        db.add_all([v for k, v in u.items() if k != "tl"])
        await db.flush()
        db.add_all([UserStoreAccess(user_id=u["owner"].id, store_id=a.id),
                     UserStoreAccess(user_id=u["owner"].id, store_id=b.id)])

        today = date.today()
        db.add_all([
            McpDailySale(store_id=a.id, date=today, revenue=15000, units_sold=3),
            McpDailySale(store_id=c.id, date=today, revenue=99999, units_sold=9),
        ])
        now = datetime.utcnow() - timedelta(minutes=5)
        l1 = TeleCallLead(sheet_tl_name="Kerala", full_name="Arjun", phone="1", status="Sale Conversion",
                          sale_amount="12,000", salesperson="sam sales", owner_user_id=u["sam"].id,
                          store_id=a.id, created_at=now, submitted_at=now)
        l2 = TeleCallLead(sheet_tl_name="Kerala", full_name="Leena", phone="2", status="",
                          owner_user_id=u["tia"].id, store_id=b.id, created_at=now, submitted_at=now)
        l3 = TeleCallLead(sheet_tl_name="Chennai", full_name="Noah", phone="3", status="Appointment",
                          store_id=c.id, created_at=now, submitted_at=now)
        l4 = TeleCallLead(sheet_tl_name="Kerala", full_name="Maya", phone="4", status="Will Visit",
                          created_at=now, submitted_at=now)
        db.add_all([l1, l2, l3, l4])
        await db.flush()
        db.add(TeleAppointment(lead_id=l4.id, store_id=b.id, scheduled_at=datetime.utcnow() + timedelta(days=1)))
        db.add(StoreStaff(store_id=a.id, month=today.strftime("%Y-%m"), manager_name="Mini", staff_count=4,
                          total_headcount=5))
        await db.commit()
        ids = {k: v.id for k, v in u.items()}

    state = {"user": None}

    async def _db():
        async with Session() as s:
            yield s

    async def _user():
        async with Session() as s:
            return (await s.execute(
                select(User).where(User.id == state["user"]).options(selectinload(User.store_access))
            )).scalar_one()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        def as_user(key):
            state["user"] = ids[key]
            return client
        yield as_user
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_sees_only_their_stores(env):
    r = await env("owner").get("/api/v1/store-owner/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["name"] for s in body["stores"]] == ["Kerala Kochi", "Mysore"]

    # Sales: MCP revenue for Kochi only — Velachery's 99,999 isn't theirs.
    assert body["sales"]["total_revenue"] == 15000
    assert {s["store"] for s in body["sales"]["by_store"]} == {"Kerala Kochi", "Mysore"}

    # Leads: Kochi's, Mysore's, and Maya (no store, but booked into Mysore).
    leads = body["leads"]
    assert {l["name"] for l in leads["recent"]} == {"Arjun", "Leena", "Maya"}
    assert next(l for l in leads["recent"] if l["name"] == "Maya")["store"] == "Mysore"
    assert leads["kpis"]["total_leads"] == 3 and leads["kpis"]["converted"] == 1
    assert leads["upcoming_appointments"] == 1
    by_store = {s["store"]: s["total_leads"] for s in leads["by_store"]}
    assert by_store == {"Kerala Kochi": 1, "Mysore": 2}

    # Staff: people linked to the two stores plus their team leader.
    staff = {s["name"]: s for s in body["staff"]}
    assert set(staff) == {"Tara Lead", "Sam Sales", "Tia Caller"}
    assert staff["Sam Sales"]["sales_closed"] == 1 and staff["Sam Sales"]["sales_amount"] == 12000
    assert staff["Sam Sales"]["total_leads"] == 1 and staff["Sam Sales"]["measured"]
    assert staff["Tia Caller"]["stores"] == ["Mysore"]
    assert staff["Tara Lead"]["stores"] == ["Kerala Kochi", "Mysore"] and not staff["Tara Lead"]["measured"]
    assert body["staff_records"][0]["manager_name"] == "Mini"


@pytest.mark.asyncio
async def test_other_roles_are_refused(env):
    r = await env("tl").get("/api/v1/store-owner/overview")
    assert r.status_code == 403
