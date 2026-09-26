"""API-level tests for the telecalling CRM and the extended role dashboards,
run through the real FastAPI app against in-memory SQLite (auth and the DB
session are overridden). Checks role scoping, the main CRM flows, and that
the existing response keys of the old endpoints are all still there.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
from datetime import datetime, timedelta

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.deps import get_current_user  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    Permission, Role, RolePermission, Setting, TeleCallLead, TeleSheetAssignment, User,
)
from app.services.crm.timeutil import from_ist, utcnow  # noqa: E402

PERMS = {
    "Telecaller": [("dashboard", "view"), ("leads", "view"), ("leads", "edit")],
    "Team Leader": [("dashboard", "view"), ("leads", "view"), ("leads", "edit")],
    "Admin": [("dashboard", "view"), ("leads", "view"), ("leads", "edit"), ("leads", "export"),
              ("settings", "edit")],
}


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        perm_rows = {}
        roles = {}
        for role_name, perms in PERMS.items():
            role = Role(name=role_name)
            db.add(role)
            await db.flush()
            roles[role_name] = role
            for res, act in perms:
                if (res, act) not in perm_rows:
                    p = Permission(resource=res, action=act)
                    db.add(p)
                    await db.flush()
                    perm_rows[(res, act)] = p
                db.add(RolePermission(role_id=role.id, permission_id=perm_rows[(res, act)].id))
        users = {
            "tl": User(name="Tara Lead", email="tl@x", password_hash="x", role_id=roles["Team Leader"].id),
            "sureka": User(name="Sureka K", email="s@x", password_hash="x", role_id=roles["Telecaller"].id),
            "riya": User(name="Riya Menon", email="r@x", password_hash="x", role_id=roles["Telecaller"].id),
            "sam": User(name="Sam B", email="sam@x", password_hash="x", role_id=roles["Telecaller"].id),
            "admin": User(name="Ada Admin", email="a@x", password_hash="x", role_id=roles["Admin"].id),
        }
        db.add_all(users.values())
        await db.flush()
        for key in ("tl", "sureka", "riya"):
            db.add(TeleSheetAssignment(user_id=users[key].id, sheet_tl_name="Kerala"))
        db.add(TeleSheetAssignment(user_id=users["sam"].id, sheet_tl_name="Chennai"))
        db.add(Setting(key="crm.go_live_at", value='"2026-01-01T00:00:00"'))
        now = utcnow()
        tomorrow_ist = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        db.add_all([
            TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="k", full_name="Arjun Mehta", phone="9876500001",
                         status="Call back later", person_calling="Sureka K", owner_user_id=users["sureka"].id,
                         stage="contacting", priority="warm", created_at=now, submitted_at=now),
            TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="k", full_name="Leena Rao", phone="9876500002",
                         status="", stage="new", priority="warm", created_at=now, submitted_at=now,
                         appointment_date=tomorrow_ist),
            TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="k", full_name="Maya Iyer", phone="9876500003",
                         status="Sale Conversion", sale_amount="12,000", owner_user_id=users["riya"].id,
                         stage="converted", priority="warm", created_at=now, submitted_at=now),
            TeleCallLead(sheet_tl_name="Chennai", spreadsheet_id="c", full_name="Noah F", phone="9876500004",
                         status="Not Interested", owner_user_id=users["sam"].id, stage="not_interested",
                         priority="cold", created_at=now, submitted_at=now),
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
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        def as_user(key):
            state["user"] = ids[key]
            return client
        yield as_user, ids
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_telecaller_sees_city_and_my_leads(env):
    as_user, ids = env
    c = as_user("sureka")
    r = await c.get("/api/v1/crm/leads")
    assert r.status_code == 200, r.text
    body = r.json()
    names = {i["full_name"] for i in body["items"]}
    assert names == {"Arjun Mehta", "Leena Rao", "Maya Iyer"}      # whole Kerala sheet, not Chennai
    assert body["tab_counts"]["mine"] == 1 and body["tab_counts"]["unassigned"] == 1
    assert body["status_counts"]["No Status"] == 1
    r = await c.get("/api/v1/crm/leads", params={"tab": "mine"})
    assert [i["full_name"] for i in r.json()["items"]] == ["Arjun Mehta"]
    r = await c.get("/api/v1/crm/leads", params={"status": "No Status"})
    assert [i["full_name"] for i in r.json()["items"]] == ["Leena Rao"]


@pytest.mark.asyncio
async def test_log_activity_claims_and_schedules(env):
    as_user, ids = env
    c = as_user("sureka")
    leads = (await c.get("/api/v1/crm/leads", params={"q": "Leena"})).json()["items"]
    lead_id = leads[0]["id"]
    r = await c.post(f"/api/v1/crm/leads/{lead_id}/activities", json={"outcome": "no_answer", "notes": "rang out"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["lead"]["status"] == "Call Not Connected"
    assert data["lead"]["owner_user_id"] == ids["sureka"]   # agent working an unowned lead takes it
    assert data["next_follow_up"]["kind"] == "call"
    detail = (await c.get(f"/api/v1/crm/leads/{lead_id}")).json()
    kinds = [t["type"] for t in detail["timeline"]]
    assert "call" in kinds and "assignment" in kinds and "milestone" in kinds
    r = await c.post(f"/api/v1/crm/leads/{lead_id}/activities", json={"outcome": "callback_requested"})
    assert r.status_code == 400  # needs the customer's time


@pytest.mark.asyncio
async def test_only_team_leader_reassigns(env):
    as_user, ids = env
    lead_id = (await as_user("sureka").get("/api/v1/crm/leads", params={"q": "Arjun"})).json()["items"][0]["id"]
    r = await as_user("sureka").post(f"/api/v1/crm/leads/{lead_id}/assign", json={"owner_user_id": ids["riya"]})
    assert r.status_code == 403
    r = await as_user("tl").post(f"/api/v1/crm/leads/{lead_id}/assign", json={"owner_user_id": ids["sam"]})
    assert r.status_code == 400  # Sam is on the Chennai team
    r = await as_user("tl").post(f"/api/v1/crm/leads/{lead_id}/assign", json={"owner_user_id": ids["riya"]})
    assert r.status_code == 200 and r.json()["lead"]["owner_name"] == "Riya Menon"
    audit = (await as_user("admin").get("/api/v1/crm/audit")).json()["items"]
    assert audit[0]["action"] == "reassign"


@pytest.mark.asyncio
async def test_new_lead_price_book_and_pipeline(env):
    as_user, ids = env
    admin = as_user("admin")
    r = await admin.put("/api/v1/crm/price-book", json={
        "phone_model": "iPhone 15", "service_type": "Screen repair",
        "prices": {"Standard": 18000, "AppleCare+": 14000, "Samsung Care+": None}})
    assert r.status_code == 200, r.text
    book = (await admin.get("/api/v1/crm/price-book")).json()
    assert book["rows"][0]["prices"]["Standard"] == 18000.0

    c = as_user("sureka")
    r = await c.post("/api/v1/crm/leads", json={"full_name": "Walk In", "phone": "9000000000", "city": "Kerala",
                                                 "phone_model": "iPhone 15", "service_type": "Screen repair",
                                                 "coverage": "AppleCare+"})
    assert r.status_code == 200, r.text
    lead = r.json()["lead"]
    assert lead["potential_value"] == 14000.0 and lead["owner_user_id"] == ids["sureka"]
    assert lead["first_call_pending"] and not lead["from_sheet"]
    r = await c.post("/api/v1/crm/leads", json={"full_name": "X", "phone": "9000000001", "city": "Chennai"})
    assert r.status_code == 403  # not her city

    r = await c.patch(f"/api/v1/crm/leads/{lead['id']}", json={"stage": "paid_advance"})
    assert r.json()["lead"]["priority"] == "hot"
    cols = {col["stage"]: col for col in (await c.get("/api/v1/crm/pipeline")).json()["columns"]}
    assert cols["paid_advance"]["count"] == 1 and cols["paid_advance"]["value"] == 14000.0
    assert cols["converted"]["value"] == 12000.0
    c = as_user("sureka")
    assert (await c.put("/api/v1/crm/price-book", json={
        "phone_model": "a", "service_type": "b", "prices": {}})).status_code == 403


@pytest.mark.asyncio
async def test_daily_pages(env):
    as_user, ids = env
    c = as_user("tl")
    ov = (await c.get("/api/v1/crm/overview")).json()
    assert set(ov["tiles"]) == {"first_contact_pending", "due_today", "overdue", "unassigned"}
    assert ov["tiles"]["unassigned"] == 1 and len(ov["pipeline"]) == 6
    fu = (await c.get("/api/v1/crm/followups")).json()
    assert set(fu) >= {"overdue", "today", "upcoming"}
    ap = (await c.get("/api/v1/crm/appointments")).json()
    sheet_appts = [i for col in ap["columns"] for i in col["items"] if i["source"] == "sheet"]
    assert [a["lead_name"] for a in sheet_appts] == ["Leena Rao"]   # read from the sheet's date text
    lead_id = sheet_appts[0]["lead_id"]
    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=11, minute=30).isoformat(timespec="minutes")
    r = await c.post("/api/v1/crm/appointments", json={"lead_id": lead_id, "scheduled_at": tomorrow})
    assert r.status_code == 200, r.text
    r = await c.patch(f"/api/v1/crm/appointments/{r.json()['id']}", json={"attendance": "no_show"})
    assert r.status_code == 200
    assert (await c.get("/api/v1/crm/alerts")).status_code == 200
    rep = (await c.get("/api/v1/crm/reports/agents")).json()
    assert {r["name"] for r in rep["rows"]} == {"Sureka K", "Riya Menon"}   # TL's team only
    me = (await as_user("sureka").get("/api/v1/crm/reports/agents")).json()
    assert [r["name"] for r in me["rows"]] == ["Sureka K"]                   # telecaller: self only
    c = as_user("tl")
    assert (await c.post("/api/v1/crm/reports/coach", json={"user_id": ids["sureka"], "note": "Call faster"})).status_code == 200
    alerts = (await as_user("sureka").get("/api/v1/crm/alerts")).json()
    assert alerts["performance"][0]["kind"] == "coaching"


@pytest.mark.asyncio
async def test_admin_settings_tabs_and_export(env):
    as_user, ids = env
    a = as_user("admin")
    s = (await a.get("/api/v1/crm/settings/automation")).json()
    assert s["automation"]["first_call_minutes"] == 5 and s["can_edit"]
    r = await a.put("/api/v1/crm/settings/automation", json={"automation": {"first_call_minutes": 30}})
    assert r.status_code == 400  # must stay ≤ reassign minutes
    r = await a.put("/api/v1/crm/settings/automation", json={"automation": {"first_call_minutes": 4}})
    assert r.status_code == 200 and r.json()["automation"]["first_call_minutes"] == 4
    assert (await as_user("tl").put("/api/v1/crm/settings/automation", json={"targets": {}})).status_code == 403
    a = as_user("admin")
    dq = (await a.get("/api/v1/crm/data-quality")).json()
    assert dq["unassigned_open"]["count"] == 1
    integ = (await a.get("/api/v1/crm/integrations")).json()
    assert {s["city"] for s in integ["sheets"]} >= {"Kerala", "Chennai"}
    csv = await a.get("/api/v1/crm/reports/export")
    assert csv.status_code == 200 and "Arjun Mehta" in csv.text
    assert (await as_user("tl").get("/api/v1/crm/reports/export")).status_code == 403
    a = as_user("admin")
    assert (await a.put("/api/v1/crm/settings/aliases", json={"alias": "Suri", "user_id": ids["sureka"]})).status_code == 200


@pytest.mark.asyncio
async def test_old_dashboards_keep_every_key(env):
    as_user, ids = env
    tc = (await as_user("sureka").get("/api/v1/dashboard/telecaller")).json()
    for key in ("kpi", "status_breakdown", "recent_leads", "daily_calls", "ai_summary"):
        assert key in tc
    for key in ("total_leads", "converted", "appointments", "will_visit", "conversion_pct",
                "total_sale_amount", "calls_connected", "calls_not_connected", "call_back_later"):
        assert key in tc["kpi"]
    assert {"my", "city", "today", "period"} <= set(tc)
    assert "Unknown" not in {s["status"] for s in tc["status_breakdown"]}
    assert tc["kpi"]["calls_connected"] == 2   # No Status lead no longer counted as connected
    assert tc["my"]["total_leads"] == 1 and tc["city"]["kpi"]["total_leads"] == 3

    tl = (await as_user("tl").get("/api/v1/dashboard/team-leader")).json()
    for key in ("stores", "kpi", "lead_funnel", "telecaller_performance", "revenue_trend"):
        assert key in tl
    assert {"team_status_matrix", "agents", "unassigned", "today"} <= set(tl)
    assert tl["lead_funnel"].get("No Status") == 1 and "Unknown" not in tl["lead_funnel"]
    perf = {t["name"]: t for t in tl["telecaller_performance"]}
    assert perf["Sureka K"]["calls_connected"] == 1
    assert perf["Unassigned"]["calls_connected"] == 0   # was wrongly 1 before the fix


@pytest.mark.asyncio
async def test_old_leads_endpoints(env):
    as_user, ids = env
    c = as_user("sureka")
    data = (await c.get("/api/v1/tele-call-leads")).json()
    assert data["total"] == 3 and "Kerala" in data["tl_groups"]
    lead = next(l for l in data["tl_groups"]["Kerala"]["leads"] if l["full_name"] == "Leena Rao")
    r = await c.put(f"/api/v1/tele-call-leads/{lead['id']}", json={"status": "Will Visit", "person_calling": "Riya Menon"})
    assert r.status_code == 200 and r.json()["lead"]["status"] == "Will Visit"
    detail = (await c.get(f"/api/v1/crm/leads/{lead['id']}")).json()
    assert detail["lead"]["owner_name"] == "Riya Menon" and detail["lead"]["stage"] == "qualified"
    summ = (await c.get("/api/v1/tele-call-leads/status-summary", params={"owner": "me"})).json()
    assert summ["summary"]["Kerala"]["statuses"] == {"Call back later": 1}
    assert (await c.get("/api/v1/tele-call-leads/live")).status_code == 403
