"""Team leader ranking: the scoring rules, and who sees what through
GET /tl-ranking (in-memory SQLite, auth and DB overridden).

Needs `aiosqlite` for the API tests: pip install aiosqlite
"""
from datetime import date, timedelta

import pytest

from app.services import tl_ranking as scoring
from app.services.tl_ranking import Entry


# ── Scoring rules ────────────────────────────────────────────────────
def test_overall_scales_weights_over_areas_with_data():
    assert scoring.overall({"sales": 80, "tele": 60, "leads": 50, "conv": 40}) == 63.0  # 32+15+10+6
    # telecalling has no data: the other three weights are scaled to 100%
    assert scoring.overall({"sales": 80, "tele": None, "leads": 50, "conv": 40}) == 64.0  # (32+10+6)/0.75
    assert scoring.overall({"sales": None, "tele": None, "leads": None, "conv": None}) is None


def test_sales_averages_stores_and_caps_each_at_100():
    stores = [{"revenue": 300, "target": 100}, {"revenue": 50, "target": 100}, {"revenue": 10, "target": 0}]
    assert scoring.sales_score(stores) == 75.0  # (100 + 50) / 2; the store with no target is left out
    assert scoring.sales_score([{"revenue": 10, "target": 0}]) is None


def test_area_scores():
    assert scoring.leads_score(150, 300) == 50.0
    assert scoring.leads_score(150, 0) is None
    assert scoring.tele_score(80, None, 60) == 70.0
    assert scoring.conv_score(5.0, 10.0, 30.0) == 50.0  # (50 + 50) / 2
    assert scoring.conv_score(None, 10.0, None) is None


def test_rating_and_weakest():
    assert [scoring.rating(s) for s in (90, 72, 61, 45, 10, None)] == ["Excellent", "Good", "Average", "Needs work", "Poor", None]
    assert scoring.weakest({"sales": 70, "tele": 40, "leads": None, "conv": 55}) == "tele"
    assert scoring.weakest({"sales": 40, "tele": 40, "leads": 90, "conv": 90}) == "sales"  # tie: heavier area


def test_previous_window():
    assert scoring.previous_window(date(2026, 10, 1), date(2026, 10, 15)) == (date(2026, 9, 1), date(2026, 9, 15), "same days last month")
    # 31 March compares with the whole of February, never an invalid 31 Feb
    assert scoring.previous_window(date(2026, 3, 1), date(2026, 3, 31))[:2] == (date(2026, 2, 1), date(2026, 2, 28))
    assert scoring.previous_window(date(2026, 10, 9), date(2026, 10, 15)) == (date(2026, 10, 2), date(2026, 10, 8), "previous 7 days")
    assert scoring.previous_window(date(2026, 10, 15), date(2026, 10, 15))[2] == "previous 1 day"


def test_rank_orders_by_score_and_puts_no_data_last():
    rows = scoring.rank([
        Entry(1, "Asha", {"sales": 50, "tele": None, "leads": None, "conv": None}, previous_score=40.0),
        Entry(2, "Bala", {"sales": None, "tele": None, "leads": None, "conv": None}),
        Entry(3, "Chitra", {"sales": 90, "tele": None, "leads": None, "conv": None}),
    ])
    assert [(r["name"], r["rank"]) for r in rows] == [("Chitra", 1), ("Asha", 2), ("Bala", None)]
    assert rows[1]["change"] == 10.0
    assert scoring.team_average(rows)["score"] == 70.0


# ── API: who sees what ───────────────────────────────────────────────
aiosqlite = pytest.importorskip("aiosqlite")
pytest_asyncio = pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.v1 import tl_ranking as api  # noqa: E402
from app.core.deps import get_current_user  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    McpDailySale, Role, Store, StoreMcpAlias, TeleCallLead, TeleSheetAssignment, User,
)
from app.services.crm.timeutil import utcnow  # noqa: E402


@pytest_asyncio.fixture
async def env(monkeypatch):
    async def _no_mcp(*_a, **_k):
        return None
    monkeypatch.setattr(api.sales_report_service, "_ensure_mcp_coverage", _no_mcp)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    today = date.today()
    async with Session() as db:
        roles = {n: Role(name=n) for n in ("Team Leader", "Admin", "Telecaller")}
        db.add_all(roles.values())
        await db.flush()
        users = {
            "sam": User(name="SAM", email="sam@x", password_hash="x", role_id=roles["Team Leader"].id),
            "nazil": User(name="NAZIL", email="n@x", password_hash="x", role_id=roles["Team Leader"].id),
            "idle": User(name="Idle TL", email="i@x", password_hash="x", role_id=roles["Team Leader"].id),
            "placeholder": User(name="Unassigned", email="unassigned@system.local", password_hash="x",
                                role_id=roles["Team Leader"].id),
            "admin": User(name="Ada", email="a@x", password_hash="x", role_id=roles["Admin"].id),
            "caller": User(name="Cal", email="c@x", password_hash="x", role_id=roles["Telecaller"].id),
        }
        db.add_all(users.values())
        await db.flush()
        thrissur = Store(name="Thrissur", team_leader_id=users["sam"].id, monthly_target=310000)
        kochi = Store(name="Kochi", team_leader_id=users["nazil"].id, monthly_target=310000)
        spare = Store(name="Spare", team_leader_id=users["placeholder"].id)
        db.add_all([thrissur, kochi, spare])
        await db.flush()
        db.add_all([StoreMcpAlias(store_id=thrissur.id, mcp_shop_name="Thrissur MCP"),
                    StoreMcpAlias(store_id=kochi.id, mcp_shop_name="Kochi MCP")])
        # Sam sells 3x Nazil today
        db.add_all([McpDailySale(store_id=thrissur.id, date=today, revenue=9000, new_sale_count=3),
                    McpDailySale(store_id=kochi.id, date=today, revenue=3000, new_sale_count=1)])
        db.add(TeleSheetAssignment(user_id=users["sam"].id, sheet_tl_name="Thrissur"))
        now = utcnow()
        db.add_all([
            TeleCallLead(sheet_tl_name="Thrissur", spreadsheet_id="s", phone="9876500001", status="Sale Conversion",
                         created_at=now, submitted_at=now),
            TeleCallLead(sheet_tl_name="Thrissur", spreadsheet_id="s", phone="+91 98765 00001", status="",
                         created_at=now, submitted_at=now),  # same person again: counted once
        ])
        await db.commit()
        ids = {k: u.id for k, u in users.items()}

    state = {"user": None}

    async def _db():
        async with Session() as s:
            yield s

    async def _user():
        async with Session() as s:
            return await s.get(User, state["user"])

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        def as_user(key):
            state["user"] = ids[key]
            return client
        yield as_user, ids, today
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_sees_every_team_leader_with_details(env):
    as_user, ids, today = env
    r = await as_user("admin").get(f"/api/v1/tl-ranking?start={today}&end={today}")
    assert r.status_code == 200
    body = r.json()
    names = [row["name"] for row in body["rows"]]
    assert names[:2] == ["SAM", "NAZIL"]  # 9,000 vs 3,000 on the same daily target
    assert "Unassigned" not in names and "Idle TL" not in names  # placeholder, and no stores or sheets
    sam = body["rows"][0]
    assert sam["rank"] == 1 and sam["details"]["leads"]["leads"] == 1 and sam["details"]["leads"]["entries"] == 2
    assert sam["details"]["conv"]["converted"] == 1
    assert body["viewer"]["is_admin"] is True


@pytest.mark.asyncio
async def test_team_leader_sees_ranks_but_only_own_details(env):
    as_user, ids, today = env
    body = (await as_user("nazil").get(f"/api/v1/tl-ranking?start={today}&end={today}")).json()
    me = next(r for r in body["rows"] if r["team_leader_id"] == ids["nazil"])
    other = next(r for r in body["rows"] if r["team_leader_id"] == ids["sam"])
    assert me["details"] is not None and me["areas"]["sales"] is not None
    assert other["details"] is None and other["areas"] is None and other["score"] is not None
    assert body["viewer"] == {"is_admin": False, "team_leader_id": ids["nazil"]}


@pytest.mark.asyncio
async def test_other_roles_and_bad_periods_are_refused(env):
    as_user, ids, today = env
    assert (await as_user("caller").get("/api/v1/tl-ranking")).status_code == 403
    bad = await as_user("admin").get(f"/api/v1/tl-ranking?start={today}&end={today - timedelta(days=1)}")
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_future_period_has_no_scores(env):
    as_user, ids, today = env
    later = today + timedelta(days=40)
    body = (await as_user("admin").get(f"/api/v1/tl-ranking?start={later}&end={later}")).json()
    assert all(r["score"] is None and r["rank"] is None for r in body["rows"])
