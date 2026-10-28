"""Test auth and permission logic."""
import pytest
from app.core.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, decode_token,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("testpass123")
        assert verify_password("testpass123", hashed)
        assert not verify_password("wrongpass", hashed)

    def test_different_hashes(self):
        h1 = hash_password("samepass")
        h2 = hash_password("samepass")
        assert h1 != h2

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed)


class TestJWT:
    def test_access_token_decode(self):
        token = create_access_token({"sub": "1"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["type"] == "access"

    def test_refresh_token_decode(self):
        token = create_refresh_token({"sub": "1"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["type"] == "refresh"

    def test_invalid_token(self):
        payload = decode_token("invalid.token.here")
        assert payload is None

    def test_tampered_token(self):
        token = create_access_token({"sub": "1"})
        tampered = token[:-5] + "XXXXX"
        payload = decode_token(tampered)
        assert payload is None


class TestPermissionLogic:
    def test_permission_check_logic(self):
        perms = [
            {"resource": "dashboard", "action": "view"},
            {"resource": "operations", "action": "create"},
        ]
        assert any(p["resource"] == "dashboard" and p["action"] == "view" for p in perms)
        assert not any(p["resource"] == "dashboard" and p["action"] == "delete" for p in perms)

    def test_permission_empty(self):
        perms = []
        assert not any(p["resource"] == "dashboard" and p["action"] == "view" for p in perms)


class TestTypingAccidents:
    """A phone keyboard's space, or a capital in the email, must not make a
    correct login fail with "Invalid credentials"."""

    def test_spaces_around_a_password(self):
        import bcrypt
        hashed = hash_password("  Kochi@123 ")           # saved without the spaces
        assert verify_password("Kochi@123", hashed)
        assert verify_password("Kochi@123 ", hashed)     # keyboard added a space
        assert not verify_password("kochi@123", hashed)  # case still matters
        old = bcrypt.hashpw(b"pass word ", bcrypt.gensalt()).decode()  # saved before stripping
        assert verify_password("pass word ", old)

    def test_email_is_matched_without_spaces_or_case(self):
        from app.core.security import normalize_email
        assert normalize_email("  Kochi@BreakProtection.com ") == "kochi@breakprotection.com"
        assert normalize_email(None) == ""


@pytest.mark.asyncio
async def test_login_ignores_email_case_and_spaces_and_a_reset_password_works():
    pytest.importorskip("aiosqlite")
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from app.core.deps import get_db
    from app.db.base import Base
    from app.main import app
    from app.models.models import Role, User
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        role = Role(name="Store Staff")
        db.add(role)
        await db.flush()
        # an email saved with a stray space and capitals, as an old form allowed
        db.add(User(name="Kochi", email=" Kochi@Store.com", password_hash=hash_password("old-pass"), role_id=role.id))
        await db.commit()

    async def _db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            ok = await c.post("/api/v1/auth/login", json={"email": "kochi@store.com ", "password": "old-pass"})
            assert ok.status_code == 200, ok.text
            async with Session() as db:  # an admin reset (same hashing as /users/{id}/reset-password)
                from sqlalchemy import select
                u = (await db.execute(select(User))).scalar_one()
                u.password_hash = hash_password("New-Pass 1 ")
                await db.commit()
            assert (await c.post("/api/v1/auth/login", json={"email": "KOCHI@store.com", "password": "New-Pass 1"})).status_code == 200
            assert (await c.post("/api/v1/auth/login", json={"email": "kochi@store.com", "password": "old-pass"})).status_code == 401
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
