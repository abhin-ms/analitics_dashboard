"""Legacy store-level routes fail closed: a user with no store grants sees
nothing, a store-bound user sees only their store, a Team Leader their own
branches, and only company-wide roles see every store.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
from datetime import date, datetime

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
    DailySubmission, Lead, Permission, Role, RolePermission, Store, Task, TeleCallLead, User, UserStoreAccess,
)

ROLES = ("CEO", "Regional Manager", "Team Leader", "Telecaller", "Store Staff")
PERMS = [("dashboard", "view"), ("leads", "view"), ("tasks", "view"), ("reports", "view"),
         ("operations", "view"), ("team_leaders", "view")]


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        roles = {n: Role(name=n) for n in ROLES}
        perms = [Permission(resource=r, action=a) for r, a in PERMS]
        db.add_all([*roles.values(), *perms])
        await db.flush()
        db.add_all([RolePermission(role_id=r.id, permission_id=p.id) for r in roles.values() for p in perms])

        tl = User(name="Tara", email="tl@x", password_hash="x", role_id=roles["Team Leader"].id)
        other_tl = User(name="Omar", email="tl2@x", password_hash="x", role_id=roles["Team Leader"].id)
        db.add_all([tl, other_tl])
        await db.flush()
        a = Store(name="A", team_leader_id=tl.id, monthly_target=0)
        b = Store(name="B", team_leader_id=tl.id, monthly_target=0)
        c = Store(name="C", team_leader_id=other_tl.id, monthly_target=0)
        db.add_all([a, b, c])
        await db.flush()
        u = {
            "tl": tl,
            "ceo": User(name="Cee", email="ceo@x", password_hash="x", role_id=roles["CEO"].id),
            "rm": User(name="Rae", email="rm@x", password_hash="x", role_id=roles["Regional Manager"].id),
            "caller": User(name="Tia", email="t@x", password_hash="x", role_id=roles["Telecaller"].id,
                           store_id=a.id),
            "staff": User(name="Sol", email="s@x", password_hash="x", role_id=roles["Store Staff"].id),
        }
        db.add_all([v for k, v in u.items() if k != "tl"])
        await db.flush()
        db.add(UserStoreAccess(user_id=u["rm"].id, store_id=c.id))

        today = date.today()
        db.add_all([
            DailySubmission(store_id=a.id, date=today, revenue=100),
            DailySubmission(store_id=b.id, date=today, revenue=20),
            DailySubmission(store_id=c.id, date=today, revenue=99999),
            Lead(store_id=a.id, name="La", status="hot"),
            Lead(store_id=c.id, name="Lc", status="hot"),
            Task(title="Ta", store_id=a.id),
            Task(title="Tc", store_id=c.id),
            Task(title="Mine", assigned_to=u["staff"].id),
            TeleCallLead(sheet_tl_name="Kerala", full_name="X", phone="1", status="Appointment",
                         created_at=datetime.utcnow()),
        ])
        await db.commit()
        ids = {k: v.id for k, v in u.items()}
        store_ids = {"A": a.id, "B": b.id, "C": c.id}

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
        as_user.store_ids = store_ids
        yield as_user
    app.dependency_overrides.clear()
    await engine.dispose()


async def _revenue(env, who):
    r = await env(who).get("/api/v1/dashboard")
    assert r.status_code == 200, r.text
    return r.json()["total_revenue"]["value"]


@pytest.mark.asyncio
async def test_dashboard_revenue_is_scoped(env):
    assert await _revenue(env, "ceo") == 100119
    assert await _revenue(env, "tl") == 120            # A + B, their own branches
    assert await _revenue(env, "caller") == 100        # store A only
    assert await _revenue(env, "rm") == 99999          # granted C only
    assert await _revenue(env, "staff") == 0           # no store at all → nothing


@pytest.mark.asyncio
async def test_leads_tasks_and_submissions_are_scoped(env):
    names = lambda r: sorted(x.get("name") or x.get("title") or x.get("store_name") for x in r.json())  # noqa: E731
    assert names(await env("caller").get("/api/v1/leads/")) == ["La"]
    assert names(await env("staff").get("/api/v1/leads/")) == []
    assert names(await env("ceo").get("/api/v1/leads/")) == ["La", "Lc"]

    assert names(await env("caller").get("/api/v1/tasks/")) == ["Ta"]
    assert names(await env("staff").get("/api/v1/tasks/")) == ["Mine"]

    assert names(await env("staff").get("/api/v1/submissions/")) == []
    assert names(await env("tl").get("/api/v1/submissions/")) == ["A", "B"]


@pytest.mark.asyncio
async def test_reports_are_scoped(env):
    r = await env("caller").get("/api/v1/reports/monthly-summary")
    assert [s["store_name"] for s in r.json()["stores"]] == ["A"]
    r = await env("caller").get("/api/v1/reports/leaderboard")
    assert [x["name"] for x in r.json()["leaderboard"]] == ["Tara"]
    r = await env("staff").get("/api/v1/reports/leaderboard")
    assert r.json()["leaderboard"] == []


@pytest.mark.asyncio
async def test_single_store_needs_access(env):
    c = env.store_ids["C"]
    assert (await env("caller").get(f"/api/v1/stores/{c}")).status_code == 403
    assert (await env("rm").get(f"/api/v1/stores/{c}")).status_code == 200
    assert (await env("ceo").get(f"/api/v1/stores/{c}")).status_code == 200


@pytest.mark.asyncio
async def test_status_summary_and_ai_fail_closed(env):
    r = await env("staff").get("/api/v1/tele-call-leads/status-summary")
    assert r.json() == {"summary": {}}
    r = await env("ceo").get("/api/v1/tele-call-leads/status-summary")
    assert r.json()["summary"]

    assert (await env("caller").get("/api/v1/ai-analytics/summary")).status_code == 403
    assert (await env("rm").post("/api/v1/ai-analytics/chat", json={"message": "hi"})).status_code == 403
