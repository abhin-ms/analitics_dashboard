"""Sign-in sessions: 90-day sliding refresh cookie, renewal, and ending a
user's sessions on every device (password change, deactivation) while
logout only signs out the one browser. In-memory SQLite; the real auth
dependencies are used (only the DB session is overridden).

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token, decode_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import Permission, Role, RolePermission, User  # noqa: E402

PASSWORD = "Secret-pass-1"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", settings.JWT_SECRET_KEY or "test-secret")
    # Independent of a local .env that may still say 7 (production sets 90
    # in docker-compose.yml; the built-in default is checked separately).
    monkeypatch.setattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 90)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        admin_role = Role(name="Admin")
        staff_role = Role(name="Telecaller")
        db.add_all([admin_role, staff_role])
        await db.flush()
        for res, act in [("users", "edit"), ("users", "view")]:
            p = Permission(resource=res, action=act)
            db.add(p)
            await db.flush()
            db.add(RolePermission(role_id=admin_role.id, permission_id=p.id))
        db.add_all([
            User(name="Ada Admin", email="admin@x", password_hash=hash_password(PASSWORD), role_id=admin_role.id),
            User(name="Sam Staff", email="sam@x", password_hash=hash_password(PASSWORD), role_id=staff_role.id),
        ])
        await db.commit()

    async def _db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _db

    def client():
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def user(email):
        async with Session() as s:
            return (await s.execute(select(User).where(User.email == email))).scalar_one()

    yield client, user
    app.dependency_overrides.clear()
    await engine.dispose()


def test_default_sign_in_lasts_90_days():
    from app.core.config import Settings
    assert Settings.model_fields["REFRESH_TOKEN_EXPIRE_DAYS"].default == 90


async def _login(c, email="sam@x"):
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_login_sets_90_day_sliding_cookie_and_refresh_renews_it(env):
    client, _ = env
    async with client() as c:
        r = await _login(c)
        cookie = r.headers["set-cookie"]
        assert f"Max-Age={90 * 86400}" in cookie and "HttpOnly" in cookie
        assert decode_token(r.json()["access_token"])["tv"] == 0

        r = await c.post("/api/v1/auth/refresh")  # cookie jar sends refresh_token
        assert r.status_code == 200, r.text
        assert f"Max-Age={90 * 86400}" in r.headers["set-cookie"]  # renewed, sliding
        me = await c.get("/api/v1/auth/me", headers=_bearer(r.json()["access_token"]))
        assert me.status_code == 200 and me.json()["name"] == "Sam Staff"


@pytest.mark.asyncio
async def test_tokens_from_before_session_versions_still_work(env):
    client, user = env
    sam = await user("sam@x")
    legacy = create_access_token({"sub": str(sam.id)})  # no "tv" claim
    async with client() as c:
        r = await c.get("/api/v1/auth/me", headers=_bearer(legacy))
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_password_reset_signs_user_out_everywhere(env):
    client, user = env
    async with client() as phone, client() as laptop, client() as admin:
        phone_token = (await _login(phone)).json()["access_token"]
        laptop_token = (await _login(laptop)).json()["access_token"]
        admin_token = (await _login(admin, "admin@x")).json()["access_token"]
        sam = await user("sam@x")

        r = await admin.post(f"/api/v1/users/{sam.id}/reset-password",
                             json={"new_password": "Brand-new-pass-2"}, headers=_bearer(admin_token))
        assert r.status_code == 200, r.text

        for c, token in ((phone, phone_token), (laptop, laptop_token)):
            assert (await c.get("/api/v1/auth/me", headers=_bearer(token))).status_code == 401
            assert (await c.post("/api/v1/auth/refresh")).status_code == 401
        # The admin who did it is unaffected
        assert (await admin.get("/api/v1/auth/me", headers=_bearer(admin_token))).status_code == 200


@pytest.mark.asyncio
async def test_deactivating_a_user_ends_their_sessions(env):
    client, user = env
    async with client() as staff, client() as admin:
        await _login(staff)
        admin_token = (await _login(admin, "admin@x")).json()["access_token"]
        sam = await user("sam@x")
        r = await admin.put(f"/api/v1/users/{sam.id}", json={"is_active": False}, headers=_bearer(admin_token))
        assert r.status_code == 200, r.text
        assert (await staff.post("/api/v1/auth/refresh")).status_code == 401
        assert (await user("sam@x")).token_version == 1


@pytest.mark.asyncio
async def test_logout_only_signs_out_that_browser(env):
    client, _ = env
    async with client() as phone, client() as laptop:
        await _login(phone)
        await _login(laptop)
        r = await phone.post("/api/v1/auth/logout")
        assert r.status_code == 200
        assert (await phone.post("/api/v1/auth/refresh")).status_code == 401   # cookie gone
        assert (await laptop.post("/api/v1/auth/refresh")).status_code == 200  # still signed in


@pytest.mark.asyncio
async def test_reset_link_works_once_and_ends_other_sessions(env):
    client, user = env
    async with client() as c, client() as other_device:
        await _login(other_device)
        assert (await c.post("/api/v1/auth/forgot-password", json={"email": "sam@x"})).status_code == 200
        token = (await user("sam@x")).invite_token
        assert decode_token(token)["type"] == "password_reset"
        # a reset token is not a login pass
        assert (await c.get("/api/v1/auth/me", headers=_bearer(token))).status_code == 401

        r = await c.post("/api/v1/auth/set-password", json={"token": token, "new_password": "Reset-pass-3"})
        assert r.status_code == 200, r.text
        r = await c.post("/api/v1/auth/set-password", json={"token": token, "new_password": "Again-pass-4"})
        assert r.status_code == 400  # single use
        assert (await other_device.post("/api/v1/auth/refresh")).status_code == 401
        r = await c.post("/api/v1/auth/login", json={"email": "sam@x", "password": "Reset-pass-3"})
        assert r.status_code == 200
