"""Website booking webhook → premium lead (in-memory SQLite; needs aiosqlite)."""
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
    CrmAlert, LeadSubmission, Permission, Role, RolePermission, Setting, Store, TeleAppointment, TeleCallLead,
    TeleLeadFollowup, TeleSheetAssignment, User,
)

KEY = "test-website-key"
BOOKING = {
    "full_name": "Anita Das", "mobile": "+91 90087 77088", "email": "anita@example.com", "country": "India",
    "state": "Kerala", "preferred_store": "Kochi", "phone_brand": "Apple", "phone_model": "iPhone 15 Pro",
    "preferred_date": "2026-10-05", "payment_id": "pay_ABC123", "payment_status": "captured", "amount": "99",
    "entry_id": "WEB-1001",
}


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setattr(settings, "WEBSITE_WEBHOOK_KEY", KEY)
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
        unassigned = User(name="Unassigned", email="u@x", password_hash="x", role_id=roles["Team Leader"].id)
        admin = User(name="Ada", email="a@x", password_hash="x", role_id=roles["Admin"].id)
        db.add_all([tl, unassigned, admin])
        await db.flush()
        kochi = Store(name="Kochi", team_leader_id=tl.id, region="Kerala", currency_code="INR")
        db.add(kochi)
        await db.flush()
        sureka = User(name="Sureka", email="s@x", password_hash="x", role_id=roles["Telecaller"].id,
                      team_leader_id=tl.id, store_id=kochi.id)  # Kochi's own telecaller
        riya = User(name="Riya", email="r@x", password_hash="x", role_id=roles["Telecaller"].id)
        other = User(name="Other", email="o@x", password_hash="x", role_id=roles["Telecaller"].id)
        db.add_all([sureka, riya, other])
        await db.flush()
        db.add(TeleSheetAssignment(user_id=tl.id, sheet_tl_name="Kerala"))
        db.add(TeleSheetAssignment(user_id=riya.id, sheet_tl_name="Kerala"))
        db.add(Store(name="Mumbai Bandra", team_leader_id=unassigned.id, region="Maharashtra", currency_code="INR"))
        db.add(Setting(key="crm.go_live_at", value='"2026-01-01T00:00:00"'))
        await db.commit()
        ids = {"tl": tl.id, "sureka": sureka.id, "riya": riya.id, "other": other.id, "admin": admin.id}

    state = {"user": ids["admin"]}

    async def _db():
        async with Session() as s:
            yield s

    async def _user():
        async with Session() as s:
            return await s.get(User, state["user"])

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, Session, ids, state
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_key_is_required(env):
    client, *_ = env
    assert (await client.post("/api/v1/public/website-leads", json=BOOKING)).status_code == 401
    assert (await client.post("/api/v1/public/website-leads?key=wrong", json=BOOKING)).status_code == 401


@pytest.mark.asyncio
async def test_failed_payments_are_kept_under_failed_payments_not_leads(env):
    """A failed / cancelled / abandoned payment is saved (with the reason)
    and listed under Failed payments — never a lead. When the same booking
    then pays, it becomes the lead as usual and shows "Paid later"."""
    client, Session, ids, state = env
    post = lambda body: client.post("/api/v1/public/website-leads", json=body, headers={"X-Api-Key": KEY})  # noqa: E731
    failed = {**BOOKING, "payment_status": "failed", "payment_error": "Card declined", "payment_id": ""}
    r = await post(failed)
    assert r.status_code == 200 and r.json() == {**r.json(), "ok": True, "status": "saved_unpaid"}
    await post({**failed, "payment_error": "Cancelled by user"})  # tried again: same booking
    await post({**BOOKING, "full_name": "Ravi K", "mobile": "9847000001", "entry_id": "WEB-2002",
                "payment_status": "abandoned", "payment_id": ""})
    async with Session() as db:
        assert (await db.execute(select(func.count(TeleCallLead.id)))).scalar() == 0
        assert set((await db.execute(select(LeadSubmission.status))).scalars()) == {"payment_failed"}

    r = (await client.get("/api/v1/crm/failed-payments")).json()
    rows = {x["name"]: x for x in r["items"]}
    assert set(rows) == {"Anita Das", "Ravi K"} and r["counts"] == {"unpaid": 2, "paid_later": 0}
    assert rows["Anita Das"] == {**rows["Anita Das"], "attempts": 2, "reason": "Cancelled by user",
                                 "payment_status": "failed", "store": "Kochi", "device": "Apple iPhone 15 Pro"}
    assert rows["Ravi K"]["payment_status"] == "abandoned"
    assert (await client.get("/api/v1/crm/meta")).json()["can"]["failed_payments"]

    r = await post(BOOKING)  # Anita retries and pays
    assert r.json()["status"] == "created"
    lead_id = r.json()["lead_id"]
    r = (await client.get("/api/v1/crm/failed-payments")).json()
    assert [x["name"] for x in r["items"]] == ["Ravi K"] and r["counts"] == {"unpaid": 1, "paid_later": 1}
    later = (await client.get("/api/v1/crm/failed-payments?show=paid_later")).json()["items"]
    assert [(x["name"], x["paid_lead_id"]) for x in later] == [("Anita Das", lead_id)]

    await post({**BOOKING, "full_name": "Meera Shah", "mobile": "9820000001", "entry_id": "WEB-3003",
                "state": "Maharashtra", "preferred_store": "Mumbai Bandra", "payment_status": "failed", "payment_id": ""})
    async with Session() as db:  # the store is matched once, when the booking arrives
        stores = {x.external_ref: x.store_id for x in (await db.execute(select(LeadSubmission))).scalars()}
        assert stores["website:WEB-3003"] is not None and stores["website:WEB-2002"] is not None
    assert {x["name"] for x in (await client.get("/api/v1/crm/failed-payments")).json()["items"]} == {"Ravi K", "Meera Shah"}

    for who in ("sureka", "tl"):  # Kochi's telecaller and team leader: Kochi's failed payments, not Mumbai's
        state["user"] = ids[who]
        assert (await client.get("/api/v1/crm/meta")).json()["can"]["failed_payments"]
        assert [x["name"] for x in (await client.get("/api/v1/crm/failed-payments")).json()["items"]] == ["Ravi K"]
    state["user"] = ids["other"]  # a telecaller with no store: nothing
    assert (await client.get("/api/v1/crm/failed-payments")).status_code == 403
    assert not (await client.get("/api/v1/crm/meta")).json()["can"]["failed_payments"]


@pytest.mark.asyncio
async def test_paid_booking_becomes_premium_lead_for_store_team(env):
    client, Session, ids, state = env
    r = await client.post("/api/v1/public/website-leads", json=BOOKING, headers={"X-Api-Key": KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "created" and body["store"] == "Kochi" and body["team_leader"] == "Michael"
    assert body["owner_user_id"] in (ids["sureka"], ids["riya"])       # Michael's team only
    async with Session() as db:
        lead = await db.get(TeleCallLead, body["lead_id"])
        assert lead.is_premium and lead.source_channel == "website" and lead.stage == "paid_advance"
        assert lead.priority == "hot" and lead.phone_model == "Apple iPhone 15 Pro" and lead.sheet_tl_name == "Kerala"
        assert lead.payment_ref == "pay_ABC123" and lead.customer_state == "Kerala"
        fu = (await db.execute(select(TeleLeadFollowup).where(TeleLeadFollowup.lead_id == lead.id))).scalar_one()
        assert fu.kind == "first_call" and fu.owner_user_id == body["owner_user_id"]
        appt = (await db.execute(select(TeleAppointment).where(TeleAppointment.lead_id == lead.id))).scalar_one()
        assert appt.source == "website"
        assert (await db.execute(select(func.count(CrmAlert.id)).where(CrmAlert.kind == "premium_lead"))).scalar() >= 1

    # the retry of the same entry does not create a second lead
    r2 = await client.post(f"/api/v1/public/website-leads?key={KEY}", json=BOOKING)
    assert r2.json()["status"] == "duplicate" and r2.json()["lead_id"] == body["lead_id"]
    # a new entry from the same person is a new lead
    r3 = await client.post(f"/api/v1/public/website-leads?key={KEY}", json={**BOOKING, "entry_id": "WEB-1002", "payment_id": "pay_2"})
    assert r3.json()["status"] == "created" and r3.json()["lead_id"] != body["lead_id"]

    # shows in the CRM as premium + Website for the team leader, not for an outside telecaller
    state["user"] = ids["tl"]
    leads = (await client.get("/api/v1/crm/leads", params={"source": "website"})).json()["items"]
    assert len(leads) == 2 and all(l["is_premium"] and l["source_label"] == "Website" for l in leads)
    state["user"] = ids["other"]
    assert (await client.get("/api/v1/crm/leads")).json()["total"] == 0


@pytest.mark.asyncio
async def test_form_post_and_store_without_team_goes_to_area_team_leader(env):
    """The store has no team leader, but the customer's state (Kerala) has
    one: that team leader gets the lead to assign by hand."""
    client, Session, ids, _ = env
    form = {**BOOKING, "preferred_store": "Mumbai Bandra", "entry_id": "WEB-2"}
    r = await client.post(f"/api/v1/public/website-leads?key={KEY}", data=form)   # form-encoded
    body = r.json()
    assert body["status"] == "created" and body["team_leader"] == "Michael" and body["owner_user_id"] == ids["tl"]
    async with Session() as db:
        alerts = (await db.execute(select(CrmAlert).where(CrmAlert.kind == "premium_lead"))).scalars().all()
        assert {a.recipient_user_id for a in alerts} == {ids["tl"]} and all(a.level == 1 for a in alerts)


@pytest.mark.asyncio
async def test_unknown_store_and_area_goes_to_admins(env):
    client, Session, ids, _ = env
    form = {**BOOKING, "preferred_store": "Kuala Lumpur", "state": "", "country": "Malaysia", "entry_id": "WEB-3"}
    body = (await client.post(f"/api/v1/public/website-leads?key={KEY}", data=form)).json()
    assert body["status"] == "created" and body["team_leader"] is None and body["owner_user_id"] is None
    async with Session() as db:
        alert = (await db.execute(select(CrmAlert).where(CrmAlert.kind == "premium_lead"))).scalar_one()
        assert alert.recipient_user_id == ids["admin"] and alert.level == 3


@pytest.mark.asyncio
async def test_missing_phone_is_rejected(env):
    client, *_ = env
    r = await client.post(f"/api/v1/public/website-leads?key={KEY}", json={**BOOKING, "mobile": "123"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_store_list_for_website(env):
    client, *_ = env
    stores = (await client.get(f"/api/v1/public/stores?key={KEY}")).json()["stores"]
    assert {s["name"] for s in stores} == {"Kochi", "Mumbai Bandra"}


@pytest.mark.asyncio
async def test_night_booking_tells_admins_now_and_telecaller_at_handover(env, monkeypatch):
    from app.models.models import CrmNotification
    from app.services.crm import intake
    from app.services.crm.night_queue import release_queue
    from app.services.crm.config import get_automation
    from app.services.crm.timeutil import from_ist
    from datetime import datetime
    client, Session, ids, _ = env
    monkeypatch.setattr(intake, "should_queue", lambda now, automation: True)
    body = (await client.post(f"/api/v1/public/website-leads?key={KEY}", json={**BOOKING, "entry_id": "WEB-NIGHT"})).json()
    assert body["status"] == "created"
    async with Session() as db:
        notes = {(n.user_id, n.kind) for n in (await db.execute(select(CrmNotification))).scalars().all()}
        assert notes == {(ids["admin"], "lead_admin")}                # admins only, at arrival
        lead = await db.get(TeleCallLead, body["lead_id"])
        assert lead.owner_user_id == lead.queued_owner_id is not None          # given to the telecaller at once…
        assert not any(k == "lead_assigned" for _, k in notes)                 # …but not disturbed at night
        await release_queue(db, from_ist(datetime(2026, 10, 26, 10, 0)), await get_automation(db))  # Monday, open
        await db.commit()
        notes = [(n.user_id, n.kind) for n in (await db.execute(select(CrmNotification))).scalars().all()]
        assert (lead.owner_user_id, "lead_assigned") in notes          # telecaller at hand-over
        assert notes.count((ids["admin"], "lead_admin")) == 1          # admin not told twice


@pytest.mark.asyncio
async def test_paid_booking_schedules_customer_store_and_telecaller_whatsapp(env, monkeypatch):
    from app.services.whatsapp import auto
    client, Session, ids, _ = env
    jobs = []
    monkeypatch.setattr(auto, "schedule", lambda job, lead_id, user_id=None: jobs.append((job, lead_id, user_id)))
    body = (await client.post(f"/api/v1/public/website-leads?key={KEY}", json={**BOOKING, "entry_id": "WEB-WA"})).json()
    assert body["status"] == "created"
    assert ("booking", body["lead_id"], None) in jobs                            # A1 customer + A2 store
    assert ("new_lead", body["lead_id"], body["owner_user_id"]) in jobs          # B1 telecaller
    jobs.clear()
    await client.post(f"/api/v1/public/website-leads?key={KEY}", json={**BOOKING, "entry_id": "WEB-WA"})
    assert jobs == []                                                            # a repeat sends nothing
