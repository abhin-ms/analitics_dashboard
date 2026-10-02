"""Meta Lead Ads webhook → CRM lead (in-memory SQLite; Graph API stubbed)."""
import hashlib
import hmac
import json

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.deps import get_current_user  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    CrmAlert, MetaFormStore, MetaLead, Permission, Role, RolePermission, Setting, Store, TeleCallLead,
    TeleLeadFollowup, TeleSheetAssignment, User,
)
from app.services.crm import meta_leads  # noqa: E402

SECRET, VERIFY = "test-app-secret", "test-verify"
URL = "/api/v1/public/meta/leads-webhook"


def lead(leadgen_id="L1", form_id="F1", adset="Kochi Edappally - 18 September 2026", prebook="yes",
         platform="ig", phone="+919008777088", created="2026-10-02T00:56:50+0000"):
    return {
        "id": leadgen_id, "created_time": created, "form_id": form_id, "platform": platform, "is_organic": False,
        "ad_id": "A1", "ad_name": f"{adset} - English", "adset_id": "S1", "adset_name": adset,
        "campaign_id": "C1", "campaign_name": "New Campaign - All Stores",
        "field_data": [
            {"name": "full_name", "values": ["Anita Das"]}, {"name": "phone_number", "values": [phone]},
            {"name": "email", "values": ["anita@example.com"]}, {"name": "city", "values": ["Kochi"]},
            {"name": '"which_phone_brand_do_you_use?"', "values": ["apple_(iphone)"]},
            {"name": "this_service_requires_a_pre-booking_fee_of_₹99,_which_will_be_adjusted_against_the_final_"
                     "service_amount._are_you_comfortable_proceeding_with_this_payment?", "values": [prebook]},
            {"name": "phone_number_verified", "values": ["true"]},
        ],
    }


def event(*leadgen_ids, form_id="F1"):
    return {"object": "page", "entry": [{"id": "PAGE", "time": 1, "changes": [
        {"field": "leadgen", "value": {"leadgen_id": i, "page_id": "PAGE", "form_id": form_id, "ad_id": "A1"}}
        for i in leadgen_ids]}]}


def signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setattr(settings, "META_APP_SECRET", SECRET)
    monkeypatch.setattr(settings, "META_VERIFY_TOKEN", VERIFY)
    store = {}  # leadgen_id → lead dict served by the fake Graph API

    async def fake_fetch(leadgen_id, page_id):
        return store[leadgen_id]

    async def fake_form_name(form_id, page_id):
        return {"F1": "Kochi Edappally - 18 September 2026 - OTP Verify", "F2": "BNP 1"}.get(form_id, "")

    monkeypatch.setattr(meta_leads, "fetch_lead", fake_fetch)
    monkeypatch.setattr(meta_leads, "fetch_form_name", fake_form_name)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        roles = {n: Role(name=n) for n in ("Admin", "Team Leader", "Telecaller")}
        db.add_all(roles.values())
        await db.flush()
        p = Permission(resource="leads", action="view")
        db.add(p)
        await db.flush()
        for r in roles.values():
            db.add(RolePermission(role_id=r.id, permission_id=p.id))
        tl = User(name="Michael", email="m@x", password_hash="x", role_id=roles["Team Leader"].id)
        admin = User(name="Ada", email="a@x", password_hash="x", role_id=roles["Admin"].id)
        db.add_all([tl, admin])
        await db.flush()
        sureka = User(name="Sureka", email="s@x", password_hash="x", role_id=roles["Telecaller"].id, team_leader_id=tl.id)
        db.add(sureka)
        db.add(TeleSheetAssignment(user_id=tl.id, sheet_tl_name="Kerala"))
        db.add(Store(name="Kochi Edappally", team_leader_id=tl.id, region="Kerala", currency_code="INR"))
        db.add(Store(name="Thrissur", team_leader_id=tl.id, region="Kerala", currency_code="INR"))
        db.add(Setting(key="crm.go_live_at", value='"2026-01-01T00:00:00"'))
        await db.commit()
        ids = {"tl": tl.id, "sureka": sureka.id, "admin": admin.id}

    async def _db():
        async with Session() as s:
            yield s

    async def _user():
        async with Session() as s:
            return await s.get(User, ids["admin"])

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, Session, ids, store
    app.dependency_overrides.clear()
    await engine.dispose()


def test_candidate_names():
    assert meta_leads.candidate_names("Hitech City West - 18 September 2026 - OTP Verify")[0] == "Hitech City West"
    assert "Mangalore" in meta_leads.candidate_names("BNP | Leads | Forms |  Mangalore-Phone Number")
    assert "GUWAHATI" in meta_leads.candidate_names("GUWAHATI- Whatsapp-7 Sep. 2026")
    assert meta_leads.candidate_names("BNP 1") == []


@pytest.mark.asyncio
async def test_verify_handshake(env):
    client, *_ = env
    ok = await client.get(URL, params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "123"})
    assert ok.status_code == 200 and ok.text == "123"
    bad = await client.get(URL, params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})
    assert bad.status_code == 403


@pytest.mark.asyncio
async def test_unsigned_call_is_refused(env):
    client, *_ = env
    assert (await client.post(URL, json=event("L1"))).status_code == 403


@pytest.mark.asyncio
async def test_hot_instagram_lead_routed_to_store_team(env):
    client, Session, ids, store = env
    store["L1"] = lead()
    raw, headers = signed(event("L1"))
    r = await client.post(URL, content=raw, headers=headers)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["status"] == "created" and res["store"] == "Kochi Edappally" and res["owner_user_id"] == ids["sureka"]
    async with Session() as db:
        l = await db.get(TeleCallLead, res["lead_id"])
        assert l.source_channel == "instagram" and not l.is_premium
        assert l.priority == "hot" and l.priority_manual and l.sheet_tl_name == "Kerala"
        assert l.phone_brand == "Apple (iphone)" and l.external_ref == "meta:L1"
        m = (await db.execute(select(MetaLead))).scalar_one()
        assert m.is_hot and m.platform == "instagram" and m.adset_name.startswith("Kochi") and m.lead_id == l.id
        assert (await db.execute(select(MetaFormStore.match_source))).scalar() == "auto"
        assert (await db.execute(select(TeleLeadFollowup.kind))).scalar() == "first_call"
        assert (await db.execute(select(func.count(CrmAlert.id)).where(CrmAlert.kind == "hot_lead"))).scalar() >= 1

    # Meta retries the same delivery → no second lead
    r2 = await client.post(URL, content=raw, headers=headers)
    assert r2.json()["results"][0]["status"] == "duplicate"

    # shows in the CRM with its source
    rows = (await client.get("/api/v1/crm/leads", params={"source": "instagram"})).json()["items"]
    assert len(rows) == 1 and rows[0]["source_label"] == "Instagram" and rows[0]["priority"] == "hot"


@pytest.mark.asyncio
async def test_no_answer_is_warm_and_facebook(env):
    client, Session, _, store = env
    store["L2"] = lead("L2", prebook="no", platform="fb")
    raw, headers = signed(event("L2"))
    res = (await client.post(URL, content=raw, headers=headers)).json()["results"][0]
    async with Session() as db:
        l = await db.get(TeleCallLead, res["lead_id"])
        assert l.priority == "warm" and l.source_channel == "facebook"


@pytest.mark.asyncio
async def test_unmatched_form_alerts_admins_then_mapping_routes_it(env):
    client, Session, ids, store = env
    store["L3"] = lead("L3", form_id="F2", adset="BNP 1")
    raw, headers = signed(event("L3", form_id="F2"))
    res = (await client.post(URL, content=raw, headers=headers)).json()["results"][0]
    assert res["status"] == "created" and res["store"] is None and res["owner_user_id"] is None
    async with Session() as db:
        alert = (await db.execute(select(CrmAlert).where(CrmAlert.kind == "unassigned"))).scalar_one()
        assert alert.recipient_user_id == ids["admin"] and alert.level == 3
        thrissur = (await db.execute(select(Store.id).where(Store.name == "Thrissur"))).scalar()

    forms = (await client.get("/api/v1/crm/meta/forms")).json()["forms"]
    assert forms[0]["form_id"] == "F2" and forms[0]["store_id"] is None
    r = await client.put("/api/v1/crm/meta/forms/F2", json={"store_id": thrissur})
    assert r.json()["routed_leads"] == 1
    async with Session() as db:
        l = await db.get(TeleCallLead, res["lead_id"])
        assert l.owner_user_id == ids["sureka"] and l.store_id == thrissur


@pytest.mark.asyncio
async def test_webhook_merges_into_lead_already_imported_from_sheet(env):
    client, Session, _, store = env
    from datetime import datetime
    async with Session() as db:
        db.add(TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="sheet-1", full_name="Anita Das",
                            phone="p:+919008777088", created_time="2026-10-02T06:26:50+05:30",
                            submitted_at=datetime(2026, 10, 2, 0, 56, 50), source_channel="meta_sheet"))
        await db.commit()
    store["L4"] = lead("L4")
    raw, headers = signed(event("L4"))
    res = (await client.post(URL, content=raw, headers=headers)).json()["results"][0]
    assert res["status"] == "merged"
    async with Session() as db:
        assert (await db.execute(select(func.count(TeleCallLead.id)))).scalar() == 1
        l = await db.get(TeleCallLead, res["lead_id"])
        assert l.source_channel == "instagram" and l.priority == "hot" and l.store_id is not None
