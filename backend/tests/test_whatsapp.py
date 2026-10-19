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
            return {"messages": [{"id": "wamid.TEST1"}]}
        if path.endswith("message_templates"):
            return {"data": [
                {"name": "booking_received", "status": "APPROVED", "language": "en", "category": "UTILITY",
                 "components": [{"type": "BODY", "text": "Hi {{customer_name}}"}]},
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
    assert len(templates["templates"]) == 7 and templates["meta_checked"]
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
    assert "1 status update (read 1) · 1 matched" in log[1]["summary"]  # newest first: delivered, read, sent
    assert "Refused" in next(e for e in log if e["kind"] == "update" and not e["ok"])["summary"]

    await post([{"id": "wamid.TEST1", "status": "failed", "timestamp": "1792330090",
                 "errors": [{"code": 131026, "title": "Message undeliverable"}]}])
    async with Session() as s:
        m = (await s.execute(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == "wamid.TEST1"))).scalar_one()
        assert m.status == "failed" and m.error_code == "131026"
