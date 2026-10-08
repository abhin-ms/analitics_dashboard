"""Public Instagram booking page: reachable only with the submission's random
link token, scoped to its form, and only accepts the form's phase-2 fields.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.instagram.form_models import IGForm, IGFormField, IGFormSubmission, new_public_token  # noqa: E402
from app.main import app  # noqa: E402

TOKEN = new_public_token()


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        booking = IGForm(name="booking", display_name="Booking", form_type="two_phase")
        other = IGForm(name="other", display_name="Other")
        db.add_all([booking, other])
        await db.flush()
        db.add_all([
            IGFormField(form_id=booking.id, field_key="name", label="Name", phase=1),
            IGFormField(form_id=booking.id, field_key="slot", label="Slot", phase=2, field_type="select",
                        options=[{"value": "am", "label": "Morning"}, {"value": "pm", "label": "Evening"}]),
            IGFormField(form_id=booking.id, field_key="note", label="Note", phase=2, required=False),
        ])
        sub = IGFormSubmission(form_id=booking.id, ig_user_id="u1", phase1_data={"name": "Asha", "phone": "999"},
                               public_token=TOKEN)
        db.add(sub)
        await db.commit()
        ids = {"booking": booking.id, "other": other.id, "sub": sub.id}

    async def _db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, ids, Session
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_token_opens_the_form(env):
    client, ids, _ = env
    r = await client.get(f"/api/v1/instagram/forms/{ids['booking']}/public", params={"token": TOKEN})
    assert r.status_code == 200, r.text
    assert r.json()["phase1_data"]["name"] == "Asha"


@pytest.mark.asyncio
async def test_sequential_id_and_wrong_form_are_refused(env):
    client, ids, _ = env
    base = f"/api/v1/instagram/forms/{ids['booking']}"
    assert (await client.get(f"{base}/public", params={"submission_id": ids["sub"]})).status_code == 422
    assert (await client.get(f"{base}/public", params={"token": new_public_token()})).status_code == 404
    r = await client.get(f"/api/v1/instagram/forms/{ids['other']}/public", params={"token": TOKEN})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_submit_validates_against_phase2_fields(env):
    client, ids, Session = env
    url = f"/api/v1/instagram/forms/{ids['booking']}/submit"
    for bad in ({"slot": "am", "is_admin": "1"},   # unknown key
                {"slot": "midnight"},              # not an option
                {"note": "hi"},                    # required slot missing
                {"slot": "am", "note": "x" * 501},  # too long
                {"slot": {"nested": 1}}):          # not text
        r = await client.post(url, params={"token": TOKEN}, json={"phase2_data": bad})
        assert r.status_code == 422, bad

    r = await client.post(url, params={"token": TOKEN}, json={"phase2_data": {"slot": "pm", "note": " call first "}})
    assert r.status_code == 200, r.text
    async with Session() as db:
        sub = await db.get(IGFormSubmission, ids["sub"])
        assert sub.status == "completed"
        assert sub.phase2_data == {"slot": "pm", "note": "call first"}

    # a completed booking can't be overwritten
    r = await client.post(url, params={"token": TOKEN}, json={"phase2_data": {"slot": "am"}})
    assert r.json()["status"] == "completed"
    async with Session() as db:
        assert (await db.get(IGFormSubmission, ids["sub"])).phase2_data["slot"] == "pm"
