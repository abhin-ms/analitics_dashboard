"""Settings → WhatsApp: setup, numbers, test send and the delivery-status
webhook, through the real app against in-memory SQLite with Meta faked.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
import hashlib
import hmac
import json

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.deps import get_current_user  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import Permission, Role, RolePermission, Store, User, WhatsAppMessage  # noqa: E402
from app.services.whatsapp import client as wa_client  # noqa: E402

SECRET = "app-secret-123"


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        roles = {n: Role(name=n) for n in ("Admin", "CEO", "Team Leader", "Telecaller")}
        db.add_all(roles.values())
        await db.flush()
        for action in ("view", "edit"):
            p = Permission(resource="settings", action=action)
            db.add(p)
            await db.flush()
            db.add(RolePermission(role_id=roles["Admin"].id, permission_id=p.id))
        users = {
            "admin": User(name="Ada Admin", email="a@x", password_hash="x", role_id=roles["Admin"].id),
            "ceo": User(name="Cyrus CEO", email="c@x", password_hash="x", role_id=roles["CEO"].id),
            "tl": User(name="Tara Lead", email="t@x", password_hash="x", role_id=roles["Team Leader"].id),
            "tc": User(name="Sureka K", email="s@x", password_hash="x", role_id=roles["Telecaller"].id),
        }
        db.add_all(users.values())
        await db.flush()
        store = Store(name="Indiranagar", team_leader_id=users["tl"].id)
        db.add(store)
        await db.commit()
        ids = {k: u.id for k, u in users.items()}
        ids["store"] = store.id

    state = {"user": ids["admin"]}

    async def _db():
        async with Session() as s:
            yield s

    async def _user():
        async with Session() as s:
            return await s.get(User, state["user"])

    calls = []
    subscribed = []
    sent_ok = []

    async def fake_call(cfg, method, path, **kw):
        calls.append((method, path, kw))
        if path.endswith("subscribed_apps"):
            if method == "POST":
                subscribed.append({"whatsapp_business_api_data": {"id": "77", "name": "BP leads store"}})
                return {"success": True}
            return {"data": subscribed}
        if path.endswith("/messages"):
            if kw["json"]["to"] == "910000000000":
                raise wa_client.WhatsAppError("Template name does not exist in the translation", "132001")
            sent_ok.append(1)  # Meta gives every message its own id; the first one is wamid.TEST1
            return {"messages": [{"id": f"wamid.TEST{len(sent_ok)}"}]}
        if path.endswith("message_templates"):
            return {"data": [
                {"name": "booking_received", "status": "APPROVED", "language": "en", "category": "UTILITY",
                 "components": [{"type": "BODY", "text": "Hi {{customer_name}}"}]},
                # approved without its "View Lead" button, like the live account
                {"name": "telecaller_new_lead", "status": "APPROVED", "language": "en", "category": "UTILITY",
                 "components": [{"type": "BODY", "text": "New Lead {{lead_name}}"}]},
                {"name": "lead_not_attended", "status": "APPROVED", "language": "en", "category": "UTILITY",
                 "components": [{"type": "BODY", "text": "x"}, {"type": "BUTTONS", "buttons": [
                     {"type": "URL", "text": "View Lead", "url": "https://dash.breakprotection.com/leads/{{1}}"}]}]},
            ]}
        if cfg.access_token == "bad":
            raise wa_client.WhatsAppError("Invalid OAuth access token", "190")
        return {"display_phone_number": "+91 80000 00000", "verified_name": "Break Protection"}

    monkeypatch.setattr(wa_client, "_call", fake_call)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        def as_user(key):
            state["user"] = ids[key]
            return client
        yield as_user, ids, calls, Session
    app.dependency_overrides.clear()
    await engine.dispose()


async def _setup(c):
    return await c.put("/api/v1/whatsapp/config", json={
        "access_token": "EAAG-token-abcd", "phone_number_id": "1234567890", "waba_id": "999", "app_secret": SECRET})


@pytest.mark.asyncio
async def test_setup_checks_with_meta_and_hides_secrets(env):
    as_user, _, _, _ = env
    c = as_user("admin")
    r = await c.put("/api/v1/whatsapp/config", json={"access_token": "bad", "phone_number_id": "1234567890"})
    assert r.status_code == 400 and "Invalid OAuth" in r.json()["detail"]
    r = await _setup(c)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] and body["enabled"] and body["verified_name"] == "Break Protection"
    assert body["webhook_url"].endswith("/api/v1/public/whatsapp/webhook")
    assert body["verify_token"]
    assert "EAAG-token" not in json.dumps(body) and SECRET not in json.dumps(body)
    assert body["access_token_masked"].endswith("abcd")
    # saving again without the token keeps the saved one
    r = await c.put("/api/v1/whatsapp/config", json={"phone_number_id": "1234567890"})
    assert r.status_code == 200 and r.json()["access_token_masked"].endswith("abcd")
    assert r.json()["verify_token"] == body["verify_token"]
    # only settings editors
    r = await as_user("tc").put("/api/v1/whatsapp/config", json={"phone_number_id": "1234567890"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_numbers_list_users_and_save(env):
    as_user, ids, _, _ = env
    c = as_user("admin")
    r = await c.get("/api/v1/whatsapp/contacts")
    data = r.json()
    assert [u["name"] for u in data["ceo"]] == ["Cyrus CEO"]
    assert [u["name"] for u in data["team_leaders"]] == ["Tara Lead"]
    assert [u["name"] for u in data["telecallers"]] == ["Sureka K"]
    assert [s["name"] for s in data["stores"]] == ["Indiranagar"]
    r = await c.put("/api/v1/whatsapp/contacts", json={
        "ceo": [{"user_id": ids["ceo"], "phone": "98450 12345"}],
        "ceo_extra": [{"name": "MD office", "phone": "+44 7700 900123"}],
        "team_leaders": [{"user_id": ids["tl"], "phone": "9876500001"}],
        "telecallers": [{"user_id": ids["tc"], "store_id": ids["store"], "phone": "09876500002"},
                        {"user_id": ids["tc"], "store_id": None, "phone": ""}],
        "stores": [{"store_id": ids["store"], "phone": "8000000001"}],
    })
    assert r.status_code == 200 and r.json()["saved"] == 5, r.text
    data = (await c.get("/api/v1/whatsapp/contacts")).json()
    assert data["ceo"][0]["phone"] == "919845012345"
    assert data["ceo_extra"] == [{"name": "MD office", "phone": "447700900123"}]
    assert data["telecallers"][0]["rows"] == [{"store_id": ids["store"], "phone": "919876500002"}]
    assert data["stores"][0]["phone"] == "918000000001"
    r = await c.put("/api/v1/whatsapp/contacts", json={"team_leaders": [{"user_id": ids["tl"], "phone": "12345"}]})
    assert r.status_code == 400 and "Tara Lead" in r.json()["detail"]


@pytest.mark.asyncio
async def test_test_send_and_delivery_statuses(env):
    as_user, _, calls, Session = env
    c = as_user("admin")
    r = await c.post("/api/v1/whatsapp/test-send", json={"template": "booking_received", "to": "9876543210"})
    assert r.status_code == 400 and "Setup" in r.json()["detail"]
    await _setup(c)
    templates = (await c.get("/api/v1/whatsapp/templates")).json()
    assert len(templates["templates"]) == 10 and templates["meta_checked"]  # A1–A7, B1, B2, C1 (CEO report)
    assert templates["templates"][0]["meta"][0]["status"] == "APPROVED"
    assert templates["templates"][0]["meta"][0]["buttons"] == []
    b2 = next(t for t in templates["templates"] if t["name"] == "lead_not_attended")
    assert b2["meta"][0]["buttons"] == [{"type": "URL", "text": "View Lead", "dynamic": True}]

    # subscription check: not subscribed → subscribe → subscribed
    r = await c.get("/api/v1/whatsapp/webhook-check")
    assert r.json() == {"checked": True, "subscribed": False, "apps": []}
    r = await c.post("/api/v1/whatsapp/webhook-subscribe")
    assert r.status_code == 200 and r.json()["subscribed"] and r.json()["apps"] == ["BP leads store"]

    values = {"lead_name": "Priya", "lead_source": "PM", "received_time": "18 Oct 2026, 7:30 PM"}
    r = await c.post("/api/v1/whatsapp/test-send", json={
        "template": "telecaller_new_lead", "to": "9876543210", "values": values,
        "button_values": {"0": "1024"}, "include_buttons": [0]})
    assert r.status_code == 200, r.text
    assert r.json()["message"]["status"] == "accepted"
    sent = calls[-1][2]["json"]
    assert sent["to"] == "919876543210" and sent["template"]["name"] == "telecaller_new_lead"
    body, button = sent["template"]["components"]
    assert {"type": "text", "parameter_name": "lead_name", "text": "Priya"} in body["parameters"]
    assert button == {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": "1024"}]}

    # switched off: nothing is sent, details are kept; on again: sends
    r = await c.put("/api/v1/whatsapp/config/enabled", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["configured"]
    n = len(calls)
    r = await c.post("/api/v1/whatsapp/test-send", json={"template": "telecaller_new_lead", "to": "9876543210",
                                                         "values": values, "include_buttons": [0]})
    assert r.status_code == 400 and "turned off" in r.json()["detail"] and len(calls) == n
    r = await c.put("/api/v1/whatsapp/config", json={"phone_number_id": "1234567890"})
    assert r.json()["enabled"] is False  # re-saving details doesn't switch it back on
    assert (await c.put("/api/v1/whatsapp/config/enabled", json={"enabled": True})).json()["enabled"] is True

    r = await c.post("/api/v1/whatsapp/test-send", json={"template": "telecaller_new_lead", "to": "9876543210",
                                                         "values": {"lead_name": "Priya"}})
    assert r.status_code == 400 and "lead_source" in r.json()["detail"]
    r = await c.post("/api/v1/whatsapp/test-send", json={"template": "booking_received", "to": "910000000000",
                                                         "values": {n: "x" for n in ("customer_name", "booking_date", "time_slot", "mobile_model", "store_name")}})
    assert r.status_code == 400 and "translation" in r.json()["detail"]

    # webhook: verify handshake, then signed status updates
    token = (await c.get("/api/v1/whatsapp/config")).json()["verify_token"]
    r = await c.get("/api/v1/public/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    r = await c.get("/api/v1/public/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert r.status_code == 403

    def post(statuses):
        raw = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [
            {"field": "messages", "value": {"statuses": statuses}}]}]}).encode()
        sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        return c.post("/api/v1/public/whatsapp/webhook", content=raw,
                      headers={"x-hub-signature-256": sig, "content-type": "application/json"})

    r = await c.post("/api/v1/public/whatsapp/webhook", content=b"{}", headers={"x-hub-signature-256": "sha256=bad"})
    assert r.status_code == 403
    err = (await c.get("/api/v1/whatsapp/config")).json()["last_webhook_error"]
    assert err["at"] and "App secret" in err["reason"]
    assert (await post([{"id": "wamid.TEST1", "status": "sent", "timestamp": "1792330000"}])).json()["updated"] == 1
    await post([{"id": "wamid.TEST1", "status": "read", "timestamp": "1792330060"}])
    await post([{"id": "wamid.TEST1", "status": "delivered", "timestamp": "1792330030"}])  # late: never undoes read
    items = (await c.get("/api/v1/whatsapp/messages")).json()["items"]
    good = next(m for m in items if m["wa_message_id"] == "wamid.TEST1")
    assert good["status"] == "read" and good["delivered_at"] and good["read_at"] and good["sent_at"]
    failed = next(m for m in items if m["to"] == "910000000000")
    assert failed["status"] == "failed" and failed["error_code"] == "132001"
    assert (await c.get("/api/v1/whatsapp/config")).json()["last_webhook_at"]

    log = (await c.get("/api/v1/whatsapp/webhook-log")).json()["items"]
    kinds = [(e["kind"], e["ok"]) for e in log]
    assert ("verify", True) in kinds and ("verify", False) in kinds and ("update", False) in kinds
    assert not any(e["kind"] == "update" and e["ok"] for e in log)  # normal updates aren't logged
    assert "Refused" in next(e for e in log if e["kind"] == "update" and not e["ok"])["summary"]

    await post([{"id": "wamid.TEST1", "status": "failed", "timestamp": "1792330090",
                 "errors": [{"code": 131026, "title": "Message undeliverable"}]}])
    async with Session() as s:
        m = (await s.execute(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == "wamid.TEST1"))).scalar_one()
        assert m.status == "failed" and m.error_code == "131026"


@pytest.mark.asyncio
async def test_renamed_template_is_sent_under_its_new_name(env):
    """A template re-created on Meta under a new name: renamed in the
    dashboard, every send uses the new name with the same variables."""
    as_user, _, calls, _ = env
    c = as_user("admin")
    await _setup(c)
    r = await c.put("/api/v1/whatsapp/templates/B1", json={"name": "telecaller_lead_new", "language": "en"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "telecaller_lead_new" and r.json()["default_name"] == "telecaller_new_lead"
    templates = (await c.get("/api/v1/whatsapp/templates")).json()["templates"]
    assert next(t for t in templates if t["key"] == "B1")["name"] == "telecaller_lead_new"
    assert next(t for t in templates if t["key"] == "B2")["name"] == "lead_not_attended"  # others untouched

    values = {"lead_name": "Priya", "lead_source": "PM", "received_time": "18 Oct 2026, 7:30 PM"}
    r = await c.post("/api/v1/whatsapp/test-send", json={
        "template": "telecaller_lead_new", "to": "9876543210", "values": values,
        "button_values": {"0": "1024"}, "include_buttons": [0]})
    assert r.status_code == 200, r.text
    sent = calls[-1][2]["json"]["template"]
    assert sent["name"] == "telecaller_lead_new"
    assert {"type": "text", "parameter_name": "lead_name", "text": "Priya"} in sent["components"][0]["parameters"]
    r = await c.post("/api/v1/whatsapp/test-send", json={"template": "telecaller_new_lead", "to": "9876543210",
                                                         "values": values})
    assert r.status_code == 400 and "Unknown" in r.json()["detail"]  # the old name is gone

    # two purposes can't share a name, and names must be valid Meta names
    r = await c.put("/api/v1/whatsapp/templates/B2", json={"name": "telecaller_lead_new"})
    assert r.status_code == 400 and "B1" in r.json()["detail"]
    r = await c.put("/api/v1/whatsapp/templates/B2", json={"name": "Lead Not Attended!"})
    assert r.status_code == 400
    # a telecaller can't rename
    assert (await as_user("tc").put("/api/v1/whatsapp/templates/B2", json={"name": "x_y"})).status_code == 403


@pytest.mark.asyncio
async def test_automatic_messages_go_to_the_right_numbers_once(env):
    """B1 to the telecaller (their number for that store), B2 to the team
    leader, A1 to the customer and A2 to the store; each once per lead, and
    a switched-off template sends nothing."""
    from datetime import datetime
    from app.models.models import TeleCallLead
    from app.services.whatsapp import auto
    as_user, ids, calls, Session = env
    auto._meta_cache["at"] = None  # read this test's (fake) Meta templates
    c = as_user("admin")
    await _setup(c)
    r = await c.put("/api/v1/whatsapp/contacts", json={
        "team_leaders": [{"user_id": ids["tl"], "phone": "9000000001"}],
        "telecallers": [{"user_id": ids["tc"], "store_id": None, "phone": "9000000002"},
                        {"user_id": ids["tc"], "store_id": ids["store"], "phone": "9000000003"}],
        "stores": [{"store_id": ids["store"], "phone": "9000000004"}]})
    assert r.status_code == 200, r.text
    async with Session() as db:
        lead = TeleCallLead(sheet_tl_name="Website", spreadsheet_id="", full_name="Anita Das", phone="9876543210",
                            source_channel="website", is_premium=True, store_id=ids["store"], owner_user_id=ids["tc"],
                            phone_model="iPhone 15", preferred_date="2026-10-29", customer_country="India",
                            created_at=datetime(2026, 10, 27, 8, 0), submitted_at=datetime(2026, 10, 27, 8, 0))
        db.add(lead)
        await db.commit()
        lead_id = lead.id

    def sends():
        return [(kw["json"]["to"], kw["json"]["template"]["name"], kw["json"]["template"]["components"])
                for m, p, kw in calls if p.endswith("/messages")]

    async with Session() as db:
        assert await auto._run(db, "new_lead", lead_id, ids["tc"]) == ["B1:919000000003"]  # the store's row
    to, name, comps = sends()[-1]
    assert (to, name) == ("919000000003", "telecaller_new_lead")
    assert {"type": "text", "parameter_name": "lead_source", "text": "Website"} in comps[0]["parameters"]
    assert len(comps) == 1  # B1 was approved without the View Lead button: none sent (Meta error 132018)
    async with Session() as db:
        assert await auto._run(db, "new_lead", lead_id, ids["tc"]) == []  # never twice

    async with Session() as db:
        assert await auto._run(db, "not_attended", lead_id, ids["tl"]) == ["B2:919000000001"]
    to, name, comps = sends()[-1]
    assert name == "lead_not_attended"
    assert len(comps) == 1  # B2 is message only, no View Lead button
    store_name = next(x["text"] for x in comps[0]["parameters"] if x["parameter_name"] == "store_name")
    async with Session() as db:
        assert store_name == (await db.get(Store, ids["store"])).name  # the customer's store
    assert {"type": "text", "parameter_name": "customer_number", "text": "9876543210"} in comps[0]["parameters"]

    async with Session() as db:
        sent = await auto._run(db, "booking", lead_id)
    assert sent == ["A1:919876543210", "A2:919000000004"]
    a1, a2 = sends()[-2:]
    assert a1[1] == "booking_received" and {"type": "text", "parameter_name": "booking_date",
                                            "text": "29 Oct 2026"} in a1[2][0]["parameters"]
    assert a2[1] == "store_priority_booking" and [b["sub_type"] for b in a2[2][1:]] == ["quick_reply", "quick_reply"]

    # switched off: nothing goes out
    r = await c.put("/api/v1/whatsapp/auto", json={"auto": {"B2": False}})
    assert r.json()["auto"] == {"A1": True, "A2": True, "B1": True, "B2": False}
    n = len(sends())
    async with Session() as db:
        assert await auto._run(db, "not_attended", lead_id, ids["tl"]) == []
    assert len(sends()) == n
    assert (await c.get("/api/v1/whatsapp/templates")).json()["auto"]["B2"] is False
    assert (await as_user("tc").put("/api/v1/whatsapp/auto", json={"auto": {"A1": False}})).status_code == 403


@pytest.mark.asyncio
async def test_failed_message_can_be_sent_again_once(env):
    """A message Meta refused (here: a value for a button the approved
    template doesn't have, #132018) is sent again with the Resend button,
    without that button; once only, and only by someone who may edit."""
    from app.services.whatsapp import auto
    as_user, ids, calls, Session = env
    auto._meta_cache["at"] = None
    c = as_user("admin")
    await _setup(c)
    async with Session() as db:
        failed = WhatsAppMessage(to_phone="919000000002", template="telecaller_new_lead", language="en",
                                 purpose="auto:B1", status="failed", error_code="132018",
                                 params={"values": {"lead_name": "Priya", "lead_source": "Website",
                                                    "received_time": "27 Oct 2026, 04:28 PM"},
                                         "buttons": {"0": "1024"}})
        db.add(failed)
        await db.commit()
        failed_id = failed.id

    assert (await as_user("tc").post(f"/api/v1/whatsapp/messages/{failed_id}/resend")).status_code == 403
    c = as_user("admin")
    r = await c.post(f"/api/v1/whatsapp/messages/{failed_id}/resend")
    assert r.status_code == 200, r.text
    assert r.json()["message"]["status"] == "accepted"
    sent = calls[-1][2]["json"]["template"]
    assert sent["name"] == "telecaller_new_lead" and len(sent["components"]) == 1  # no button this time
    r = await c.post(f"/api/v1/whatsapp/messages/{failed_id}/resend")
    assert r.status_code == 400 and "Already sent again" in r.json()["detail"]
    new_id = (await c.get("/api/v1/whatsapp/messages")).json()["items"][0]["id"]
    r = await c.post(f"/api/v1/whatsapp/messages/{new_id}/resend")
    assert r.status_code == 400 and "Only a failed" in r.json()["detail"]


@pytest.mark.asyncio
async def test_sent_messages_filter_page_and_download(env):
    """Sent messages: filters (status, who it went to, phone / customer,
    dates in IST), pages with a total and per-status counts, and a CSV of
    exactly what the filters show."""
    from datetime import datetime
    from app.models.models import TeleCallLead, WhatsAppMessage
    as_user, ids, calls, Session = env
    async with Session() as db:
        lead = TeleCallLead(sheet_tl_name="Kochi", spreadsheet_id="", full_name="Meera Nair", phone="9847000021",
                            created_at=datetime(2026, 10, 28, 5, 0))
        db.add(lead)
        await db.flush()
        rows = [("919847000021", "booking_received", "auto:A1", "read", lead.id, datetime(2026, 10, 28, 5, 1)),
                ("919000000003", "telecaller_new_lead", "auto:B1", "delivered", lead.id, datetime(2026, 10, 28, 5, 1)),
                ("919000000001", "lead_not_attended", "auto:B2", "failed", lead.id, datetime(2026, 10, 28, 6, 0)),
                ("919876543210", "booking_received", "test", "sent", None, datetime(2026, 10, 27, 19, 0))]  # 28 Oct 00:30 IST
        for to, tpl, purpose, status, lid, at in rows:
            db.add(WhatsAppMessage(to_phone=to, template=tpl, purpose=purpose, status=status, lead_id=lid, created_at=at,
                                   error_text="Template name does not exist" if status == "failed" else None))
        for i in range(30):  # older tests, to page through
            db.add(WhatsAppMessage(to_phone="919876543210", template="booking_received", purpose="test", status="read",
                                   created_at=datetime(2026, 10, 20, 5, i)))
        await db.commit()
    c = as_user("admin")

    page = (await c.get("/api/v1/whatsapp/messages", params={"page_size": 10})).json()
    assert page["total"] == 34 and len(page["items"]) == 10 and page["items"][0]["template"] == "lead_not_attended"
    assert page["status_counts"] == {"accepted": 0, "sent": 1, "delivered": 1, "read": 31, "failed": 1}
    assert (await c.get("/api/v1/whatsapp/messages", params={"page_size": 10, "page": 4})).json()["items"].__len__() == 4

    lead_msgs = (await c.get("/api/v1/whatsapp/messages", params={"q": "meera"})).json()
    assert lead_msgs["total"] == 3 and {m["lead_name"] for m in lead_msgs["items"]} == {"Meera Nair"}
    assert (await c.get("/api/v1/whatsapp/messages", params={"q": "+91 98470 00021"})).json()["total"] == 1
    tl = (await c.get("/api/v1/whatsapp/messages", params={"recipient": "team_leader"})).json()
    assert [m["recipient"] for m in tl["items"]] == ["team_leader"] and tl["items"][0]["status"] == "failed"
    failed = (await c.get("/api/v1/whatsapp/messages", params={"status": "failed"})).json()
    assert failed["total"] == 1 and failed["status_counts"]["read"] == 31   # counts ignore the status filter
    day = (await c.get("/api/v1/whatsapp/messages", params={"start": "2026-10-28", "end": "2026-10-28"})).json()
    assert day["total"] == 4                                                 # the 00:30 IST test counts on the 28th
    assert (await c.get("/api/v1/whatsapp/messages", params={"status": "bogus"})).status_code == 400

    r = await c.get("/api/v1/whatsapp/messages/export", params={"start": "2026-10-28", "end": "2026-10-28"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("ID,Created (IST),To,Recipient,Lead") and len(lines) == 5
    assert any("team leader" in l and "Template name does not exist" in l for l in lines)
    assert (await as_user("tc").get("/api/v1/whatsapp/messages/export")).status_code == 403


def test_received_time_is_ist_12_hour():
    """"Received at" in the WhatsApp alerts: just the IST time for a lead of
    today, with the date for an older one (a night lead told next morning)."""
    from datetime import datetime
    from app.services.whatsapp.auto import received_label
    now = datetime(2026, 10, 29, 5, 0)                                                # 29 Oct, 10:30 AM IST
    assert received_label(datetime(2026, 10, 29, 3, 35), now) == "9:05 AM IST"
    assert received_label(datetime(2026, 10, 28, 17, 32), now) == "28 Oct, 11:02 PM IST"  # last night
    assert received_label(datetime(2025, 12, 31, 6, 0), now) == "31 Dec 2025, 11:30 AM IST"


@pytest.mark.asyncio
async def test_payment_link_send_open_paid_and_reports(env, monkeypatch):
    """After a call: the form is filled from the lead, Send makes a Razorpay
    link and sends WhatsApp A6 with our Pay link; opening it is noted;
    Razorpay's signed webhook marks it paid — lead Hot, visit booked,
    everyone told — and the reports count it per telecaller."""
    import hashlib
    import hmac
    import json as _json
    from datetime import datetime, timedelta
    from app.core.config import settings
    from app.models.models import CrmAlert, PaymentLink, TeleAppointment, TeleCallLead, User
    from app.services.crm import payment_links as pay
    as_user, ids, calls, Session = env
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_x")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "s")
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec")
    monkeypatch.setattr(settings, "WHATSAPP_PAY_CONFIG", "")  # this test is the payment link
    rzp = []

    async def fake_rzp(method, path, json=None):
        rzp.append((method, path, json))
        if path == "payment_links":
            return {"id": "plink_1", "short_url": "https://rzp.io/rzp/abc", "status": "created"}
        return {"status": "cancelled"}
    monkeypatch.setattr(pay, "_rzp", fake_rzp)
    async with Session() as db:
        tc = await db.get(User, ids["tc"])
        tc.team_leader_id, tc.store_id = ids["tl"], ids["store"]
        lead = TeleCallLead(sheet_tl_name="Website", spreadsheet_id="", full_name="Rahul Krishnan", phone="9847000058",
                            owner_user_id=ids["tc"], store_id=ids["store"], status="Will Visit", stage="qualified",
                            phone_model="Galaxy S24", source_channel="instagram", created_at=datetime.utcnow())
        db.add(lead)
        await db.commit()
        lead_id = lead.id
    c = as_user("admin")
    await _setup(c)
    t = as_user("tc")

    form = (await t.get(f"/api/v1/crm/leads/{lead_id}/payment-link")).json()
    assert form["enabled"] and form["can_send"] and form["form"]["customer_name"] == "Rahul Krishnan"
    assert form["form"]["phone_model"] == "Galaxy S24" and form["form"]["store_id"] == ids["store"]
    visit = (datetime.utcnow() + timedelta(days=2)).replace(hour=6, minute=0, second=0, microsecond=0)  # 11:30 IST
    r = await t.post(f"/api/v1/crm/leads/{lead_id}/payment-link", json={
        "customer_name": "Rahul K", "customer_phone": "98470 00058", "phone_model": "Galaxy S24",
        "service": "Screen + back glass", "store_id": ids["store"], "visit_at": (visit + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M")})
    assert r.status_code == 200, r.text
    link = r.json()["link"]
    assert link["status"] == "sent" and link["amount"] == 99
    created = next(j for m, p, j in rzp if p == "payment_links")
    assert created["amount"] == 9900 and created["customer"]["contact"] == "+919847000058"
    sent = calls[-1][2]["json"]["template"]
    assert sent["name"] == "payment_link"
    body, button = sent["components"]
    assert {"type": "text", "parameter_name": "customer_name", "text": "Rahul"} in body["parameters"]
    async with Session() as db:
        pl = (await db.execute(select(PaymentLink))).scalar_one()
        token = pl.token
        assert button["parameters"] == [{"type": "text", "text": token}]
        assert (await db.get(TeleCallLead, lead_id)).service_type == "Screen + back glass"   # saved to the lead

    r = await c.get(f"/api/v1/public/pay/{token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://rzp.io/rzp/abc"

    event = {"event": "payment_link.paid", "payload": {
        "payment_link": {"entity": {"id": "plink_1", "status": "paid"}},
        "payment": {"entity": {"id": "pay_123", "amount": 9900, "created_at": int(datetime.utcnow().timestamp())}}}}
    raw = _json.dumps(event).encode()
    assert (await c.post("/api/v1/public/razorpay/webhook", content=raw,
                         headers={"x-razorpay-signature": "bad"})).status_code == 401
    good = hmac.new(b"whsec", raw, hashlib.sha256).hexdigest()
    for _ in range(2):  # Razorpay retries: once only
        r = await c.post("/api/v1/public/razorpay/webhook", content=raw, headers={"x-razorpay-signature": good})
        assert r.status_code == 200
    async with Session() as db:
        pl = (await db.execute(select(PaymentLink))).scalar_one()
        assert pl.status == "paid" and pl.payment_id == "pay_123" and pl.opened_at is not None
        lead = await db.get(TeleCallLead, lead_id)
        assert lead.stage == "paid_advance" and lead.priority == "hot" and lead.status == "Appointment"
        assert (await db.execute(select(TeleAppointment).where(TeleAppointment.lead_id == lead_id))).scalars().first()
        told = {a.recipient_user_id for a in (await db.execute(select(CrmAlert).where(CrmAlert.kind == "payment_paid"))).scalars()}
        assert {ids["tc"], ids["tl"], ids["admin"]} <= told and len(told) == len(set(told))
    assert "already paid" in (await c.get(f"/api/v1/public/pay/{token}")).text

    page = (await t.get("/api/v1/crm/leads", params={"tab": "paid_call"})).json()
    assert page["tab_counts"]["paid_call"] == 1 and page["items"][0]["call_payment"]["status"] == "paid"
    summary = (await as_user("admin").get("/api/v1/crm/payment-links/summary")).json()
    assert summary["level"] == "admin" and summary["total"]["sent"] == 1 and summary["total"]["paid"] == 1
    assert summary["team_leaders"][0]["name"] == "Tara Lead" and summary["telecallers"][0]["name"] == "Sureka K"
    mine = (await as_user("tc").get("/api/v1/crm/payment-links/summary")).json()
    assert mine["level"] == "own" and mine["total"]["paid"] == 1
    paid = (await as_user("tl").get("/api/v1/crm/payment-links", params={"user_id": ids["tc"]})).json()
    assert paid["total"] == 1 and paid["items"][0]["customer_name"] == "Rahul K" and paid["items"][0]["store"] == "Indiranagar"


@pytest.mark.asyncio
async def test_pay_inside_whatsapp_review_and_pay(env, monkeypatch):
    """Pay inside WhatsApp: template A7 with the Review and Pay button
    carrying the ₹99 order (our Razorpay payment configuration); WhatsApp's
    payment webhook is confirmed with Meta's lookup before the lead is paid;
    a non-Indian number gets a payment link instead."""
    import json as _json
    from datetime import datetime
    from app.core.config import settings
    from app.models.models import PaymentLink, TeleCallLead
    from app.services.whatsapp import client as wa_client
    as_user, ids, calls, Session = env
    monkeypatch.setattr(settings, "WHATSAPP_PAY_CONFIG", "BreakProtection")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "")  # WhatsApp payments don't need the link keys
    looked = {"status": "pending"}
    orig = wa_client._call

    async def fake_call(cfg, method, path, **kw):
        if "/payments/BreakProtection/" in path:
            calls.append((method, path, kw))
            return {"payments": [{"reference_id": path.rsplit("/", 1)[1], "status": looked["status"],
                                  "amount": {"value": 9900, "offset": 100},
                                  "transactions": [{"id": "order_1", "pg_transaction_id": "pay_W1", "status": "success",
                                                    "updated_timestamp": int(datetime.utcnow().timestamp())}]}]}
        return await orig(cfg, method, path, **kw)
    monkeypatch.setattr(wa_client, "_call", fake_call)
    async with Session() as db:
        lead = TeleCallLead(sheet_tl_name="Website", spreadsheet_id="", full_name="Rahul Krishnan", phone="9847000058",
                            owner_user_id=ids["tc"], store_id=ids["store"], status="Will Visit", stage="qualified",
                            source_channel="instagram", created_at=datetime.utcnow())
        db.add(lead)
        await db.commit()
        lead_id = lead.id
    await _setup(as_user("admin"))

    form = (await as_user("tc").get(f"/api/v1/crm/leads/{lead_id}/payment-link")).json()
    assert form["modes"] == {"whatsapp": True, "link": False} and form["form"]["mode"] == "whatsapp"
    r = await as_user("tc").post(f"/api/v1/crm/leads/{lead_id}/payment-link",
                                 json={"customer_name": "Rahul", "customer_phone": "9847000058", "store_id": ids["store"]})
    assert r.status_code == 200, r.text
    assert r.json()["link"]["mode"] == "whatsapp"
    sent = next(kw["json"] for m, p, kw in reversed(calls) if p.endswith("/messages"))["template"]
    assert sent["name"] == "payment_request"
    names = {p["parameter_name"] for p in sent["components"][0]["parameters"]}
    assert names == {"customer_name", "store_name", "mobile_model", "visit_date", "visit_time"}
    assert sent["components"][0]["type"] == "body"                      # no header
    button = sent["components"][1]
    assert button["sub_type"] == "order_details" and button["index"] == "0"
    order = button["parameters"][0]["action"]["order_details"]
    pg = order["payment_settings"][0]["payment_gateway"]
    assert pg["type"] == "razorpay" and pg["configuration_name"] == "BreakProtection"
    assert order["total_amount"] == {"value": 9900, "offset": 100} == order["order"]["subtotal"]
    async with Session() as db:
        ref = (await db.execute(select(PaymentLink))).scalar_one().reference_id
    assert order["reference_id"] == ref

    async def webhook():
        raw = _json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
            "statuses": [{"id": "x", "type": "payment", "status": "captured",
                          "payment": {"reference_id": ref, "amount": {"value": 9900, "offset": 100}}}]}}]}]}).encode()
        sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        return await as_user("admin").post("/api/v1/public/whatsapp/webhook", content=raw,
                                           headers={"x-hub-signature-256": sig, "content-type": "application/json"})

    assert (await webhook()).status_code == 200      # Meta's lookup still says pending: not paid
    async with Session() as db:
        assert (await db.execute(select(PaymentLink))).scalar_one().status == "sent"
    looked["status"] = "captured"
    assert (await webhook()).status_code == 200
    async with Session() as db:
        pl = (await db.execute(select(PaymentLink))).scalar_one()
        assert pl.status == "paid" and pl.payment_id == "pay_W1"
        assert (await db.get(TeleCallLead, lead_id)).stage == "paid_advance"

    r = await as_user("tc").post(f"/api/v1/crm/leads/{lead_id}/payment-link",
                                 json={"customer_name": "Rahul", "customer_phone": "+971 50 123 4567", "mode": "whatsapp"})
    assert r.status_code == 400 and "Indian" in r.json()["detail"]


@pytest.mark.asyncio
async def test_payment_settings_saved_from_the_dashboard(env, monkeypatch):
    """Settings → WhatsApp → Payments: saved in the database with the
    secrets encrypted and shown masked; a blank secret keeps the saved one;
    the payment code uses them with nothing in the server's environment;
    telecallers can't see or change them."""
    from app.core.config import settings
    from app.models.models import Setting
    from app.services.crm import payment_links as pay
    for k in ("WHATSAPP_PAY_CONFIG", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.setattr(settings, k, "")
    as_user, ids, calls, Session = env
    c = as_user("admin")
    empty = (await c.get("/api/v1/crm/payment-settings")).json()
    assert empty["modes"] == {"whatsapp": False, "link": False}
    r = await c.put("/api/v1/crm/payment-settings", json={
        "whatsapp_config": "BreakProtection", "key_id": "rzp_test_abc123", "key_secret": "sekret-1234567890",
        "webhook_secret": "whsec-abcdef12"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["whatsapp_config"] == "BreakProtection" and v["key_secret_masked"].endswith("7890")
    assert "sekret" not in str(v) and v["modes"] == {"whatsapp": True, "link": True} and v["test_keys"]
    assert v["webhook_url"].endswith("/api/v1/public/razorpay/webhook")
    async with Session() as db:
        stored = (await db.get(Setting, "payments.config")).value
        assert "sekret" not in stored and "whsec" not in stored                 # encrypted at rest
        s = await pay.load(db)
        assert (s.key_secret, s.webhook_secret, pay.enabled()) == ("sekret-1234567890", "whsec-abcdef12", True)
    r = await c.put("/api/v1/crm/payment-settings", json={"key_secret": "", "amount": 149})  # blank keeps it
    assert r.json()["key_secret_masked"].endswith("7890") and r.json()["amount"] == 149
    assert (await c.put("/api/v1/crm/payment-settings", json={"key_id": "abc"})).status_code == 400
    t = as_user("tc")
    assert (await t.get("/api/v1/crm/payment-settings")).status_code == 403
    assert (await t.put("/api/v1/crm/payment-settings", json={"amount": 1})).status_code == 403
