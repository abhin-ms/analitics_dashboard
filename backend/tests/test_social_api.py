"""Social performance endpoint: who sees which stores, and how view targets
roll up (store override > company default > 1,000,000; a team leader's
target is the sum of their stores'). In-memory SQLite, auth overridden.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
from datetime import datetime

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
    DailyStoreTracker, Permission, Role, RolePermission, Setting, SocialViewTarget, Store, User,
    UserStoreAccess,
)

PERMS = {
    "Admin": [("dashboard", "view"), ("settings", "view"), ("settings", "edit")],
    "Team Leader": [("dashboard", "view")],
    "Store Owner": [("dashboard", "view")],
    "Store Staff": [("dashboard", "view")],
}


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        perms, roles = {}, {}
        for role_name, plist in PERMS.items():
            role = Role(name=role_name)
            db.add(role)
            await db.flush()
            roles[role_name] = role
            for res, act in plist:
                if (res, act) not in perms:
                    p = Permission(resource=res, action=act)
                    db.add(p)
                    await db.flush()
                    perms[(res, act)] = p
                db.add(RolePermission(role_id=role.id, permission_id=perms[(res, act)].id))

        u = {
            "admin": User(name="Ada", email="a@x", password_hash="x", role_id=roles["Admin"].id),
            "tl1": User(name="Tara", email="t1@x", password_hash="x", role_id=roles["Team Leader"].id),
            "tl2": User(name="Tom", email="t2@x", password_hash="x", role_id=roles["Team Leader"].id),
        }
        db.add_all(u.values())
        await db.flush()
        stores = {
            "kochi": Store(name="Kerala Kochi", team_leader_id=u["tl1"].id),
            "thrissur": Store(name="Kerala Thrissur", team_leader_id=u["tl1"].id),
            "mysore": Store(name="Mysore", team_leader_id=u["tl2"].id),
        }
        db.add_all(stores.values())
        await db.flush()
        u["owner"] = User(name="Omar", email="o@x", password_hash="x", role_id=roles["Store Owner"].id)
        u["staff"] = User(name="Sia", email="s@x", password_hash="x", role_id=roles["Store Staff"].id,
                          store_id=stores["thrissur"].id)
        db.add_all([u["owner"], u["staff"]])
        await db.flush()
        db.add_all([
            UserStoreAccess(user_id=u["owner"].id, store_id=stores["kochi"].id),
            UserStoreAccess(user_id=u["owner"].id, store_id=stores["mysore"].id),
        ])
        for key, views, yt in (("kochi", 16400, 0), ("thrissur", 1004000, 1400), ("mysore", 713000, 0)):
            db.add(DailyStoreTracker(
                store_id=stores[key].id, store_name=stores[key].name, date="2026-08-31", country="IN",
                ig_views_achieved=views, yt_views=yt, google_rating=4.5,
                sheet_updated_at=datetime(2026, 9, 1, 10, 30),
            ))
        db.add(DailyStoreTracker(store_id=stores["kochi"].id, store_name="Kerala Kochi", date="2026-07-31",
                                 ig_views_achieved=5000, sheet_updated_at=datetime(2026, 8, 1, 9, 0)))
        db.add(SocialViewTarget(store_id=stores["kochi"].id, platform="instagram", monthly_target=2_000_000))
        db.add(Setting(key="social_target_default:youtube", value="500000"))
        await db.commit()
        ids = {k: x.id for k, x in u.items()}

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


async def _perf(client, **params):
    r = await client.get("/api/v1/social/performance", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _ig_target(body):
    return sum(s["targets"]["instagram"] for s in body["stores"])


@pytest.mark.asyncio
async def test_admin_sees_every_tracker_store(env):
    body = await _perf(env("admin"))
    assert body["scope"]["kind"] == "company" and body["scope"]["can_sync"]
    assert {s["store"] for s in body["stores"]} == {"Kerala Kochi", "Kerala Thrissur", "Mysore"}
    assert body["months"] == ["2026-08", "2026-07"] and body["month"] == "2026-08"
    assert len(body["rows"]) == 3


@pytest.mark.asyncio
async def test_team_leader_sees_own_stores_and_summed_target(env):
    body = await _perf(env("tl1"))
    assert body["scope"] == {"kind": "team_leader", "label": "Your 2 stores", "can_sync": False}
    assert {s["store"] for s in body["stores"]} == {"Kerala Kochi", "Kerala Thrissur"}
    assert {r["store"] for r in body["rows"]} == {"Kerala Kochi", "Kerala Thrissur"}
    # Kochi has a 2M override, Thrissur uses the 1M default.
    assert _ig_target(body) == 3_000_000
    assert all(s["targets"]["youtube"] == 500_000 for s in body["stores"])
    assert all(s["targets"]["facebook"] == 1_000_000 for s in body["stores"])


@pytest.mark.asyncio
async def test_store_owner_sees_linked_stores(env):
    body = await _perf(env("owner"))
    assert body["scope"]["kind"] == "store"
    assert {s["store"] for s in body["stores"]} == {"Kerala Kochi", "Mysore"}


@pytest.mark.asyncio
async def test_store_staff_sees_only_their_store_with_last_update(env):
    body = await _perf(env("staff"))
    assert body["scope"]["label"] == "Kerala Thrissur"
    [store] = body["stores"]
    assert store["last_updated_at"] == "2026-09-01T10:30:00Z"
    assert store["last_period"] == "2026-08-31"
    assert [r["store"] for r in body["rows"]] == ["Kerala Thrissur"]


@pytest.mark.asyncio
async def test_month_param_and_last_update_across_months(env):
    body = await _perf(env("admin"), month="2026-07")
    assert [r["store"] for r in body["rows"]] == ["Kerala Kochi"]
    kochi = next(s for s in body["stores"] if s["store"] == "Kerala Kochi")
    assert kochi["last_updated_at"] == "2026-09-01T10:30:00Z"  # latest change in any month


@pytest.mark.asyncio
async def test_admin_sets_targets_others_cannot(env):
    r = await env("tl1").put("/api/v1/social/targets", json={"defaults": {"instagram": 5}})
    assert r.status_code == 403

    admin = env("admin")
    targets = (await admin.get("/api/v1/social/targets")).json()
    kochi_id = next(s["store_id"] for s in targets["stores"] if s["store"] == "Kerala Kochi")
    assert targets["defaults"] == {"instagram": 1_000_000, "youtube": 500_000, "facebook": 1_000_000}

    r = await admin.put("/api/v1/social/targets", json={
        "defaults": {"instagram": 1_500_000},
        "overrides": [
            {"store_id": kochi_id, "platform": "instagram", "monthly_target": None},
            {"store_id": kochi_id, "platform": "facebook", "monthly_target": 250_000},
        ],
    })
    assert r.status_code == 200, r.text
    body = await _perf(env("tl1"))
    assert _ig_target(body) == 3_000_000  # both stores now on the 1.5M default
    kochi = next(s for s in body["stores"] if s["store"] == "Kerala Kochi")
    assert kochi["targets"]["facebook"] == 250_000

    r = await env("admin").put("/api/v1/social/targets", json={
        "overrides": [{"store_id": kochi_id, "platform": "tiktok", "monthly_target": 1}]})
    assert r.status_code == 400
