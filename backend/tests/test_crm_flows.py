"""End-to-end tests of the telecalling CRM flows against an in-memory SQLite
database: sheet sync hooks, the 5/15/60-minute automation, outcome logging
and metrics attribution. Google Sheets is replaced by a stub; nothing
touches the real MySQL database.

Needs the `aiosqlite` package (skipped when it isn't installed):
    pip install aiosqlite
"""
from datetime import date, datetime, timedelta

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import pytest_asyncio  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.models.models import (  # noqa: E402
    CrmAlert, Role, Setting, TeleCallLead, TeleLeadActivity, TeleLeadFollowup, TeleSheetAssignment, User,
)
from app.services import tele_call_sync  # noqa: E402
from app.services.crm import automation as crm_automation  # noqa: E402
from app.services.crm.config import DEFAULT_AUTOMATION, get_automation, get_targets  # noqa: E402
from app.services.crm.engine import log_outcome  # noqa: E402
from app.services.crm.metrics import agent_report  # noqa: E402
from app.services.crm.timeutil import from_ist  # noqa: E402

SHEET = {"spreadsheet_id": "sheet-kerala", "tl_name": "Kerala"}


def ist(y, m, d, h=0, mi=0):
    return from_ist(datetime(y, m, d, h, mi))


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def team(db):
    roles = {n: Role(name=n) for n in ("Telecaller", "Team Leader", "Admin")}
    db.add_all(roles.values())
    await db.flush()
    tl = User(name="Tara Lead", email="tl@x", password_hash="x", role_id=roles["Team Leader"].id)
    sureka = User(name="Sureka K", email="s@x", password_hash="x", role_id=roles["Telecaller"].id)
    riya = User(name="Riya Menon", email="r@x", password_hash="x", role_id=roles["Telecaller"].id)
    admin = User(name="Ada Admin", email="a@x", password_hash="x", role_id=roles["Admin"].id)
    db.add_all([tl, sureka, riya, admin])
    await db.flush()
    for u in (tl, sureka, riya):
        db.add(TeleSheetAssignment(user_id=u.id, sheet_tl_name="Kerala"))
    await db.commit()
    return {"tl": tl, "sureka": sureka, "riya": riya, "admin": admin}


def row(name, phone, created, person="", status="", product=""):
    return {"lead_source": "Meta", "created_time": created, "full_name": name, "phone": phone,
            "email": "", "person_calling": person, "status": status, "call_date": "",
            "appointment_date": "", "remarks": "", "sale_amount": "", "product": product}


@pytest.fixture
def sheet(monkeypatch):
    rows: list[dict] = []
    monkeypatch.setattr(tele_call_sync, "TELE_CALL_SHEETS", [SHEET])
    monkeypatch.setattr(tele_call_sync, "_fetch_sheet_rows", lambda _sid, _tab=None: [dict(r) for r in rows])
    return rows


async def count(db, model, *where):
    return (await db.execute(select(func.count(model.id)).where(*where))).scalar()


@pytest.mark.asyncio
async def test_first_sync_is_a_quiet_backfill(db, team, sheet):
    sheet += [row("Arjun Mehta", "9876500001", "2026-09-20T10:00:00+05:30", person="sureka k",
                  status="call back later"),
              row("Leena Rao", "9876500002", "2026-09-21T10:00:00+05:30")]
    await tele_call_sync.sync_tele_call_leads(db)

    leads = (await db.execute(select(TeleCallLead).order_by(TeleCallLead.id))).scalars().all()
    assert len(leads) == 2
    arjun, leena = leads
    assert arjun.status == "Call back later"            # normalised
    assert arjun.sheet_status_raw == "call back later"  # raw kept
    assert arjun.owner_user_id == team["sureka"].id     # matched from "Person Calling"
    assert arjun.stage == "contacting" and arjun.priority == "warm"
    assert arjun.submitted_at == ist(2026, 9, 20, 10, 0)
    # historic and no "Person Calling": quietly given to someone on the team, like any lead
    assert leena.owner_user_id is not None and leena.assignment_source == "store_tl"
    # historic rows get no SLA timers, no alerts and no timeline noise
    assert await count(db, TeleLeadFollowup) == 0
    assert await count(db, CrmAlert) == 0
    assert await count(db, TeleLeadActivity) == 0


@pytest.mark.asyncio
async def test_new_lead_is_assigned_and_gets_a_first_call_task(db, team, sheet):
    sheet.append(row("Old Lead", "9876500001", "2026-09-01T10:00:00+05:30"))
    await tele_call_sync.sync_tele_call_leads(db)          # go-live
    now_ist = datetime.now()
    sheet.append(row("Sara Joseph", "9876500003", now_ist.strftime("%Y-%m-%d %H:%M")))
    result = await tele_call_sync.sync_tele_call_leads(db)

    sara = (await db.execute(select(TeleCallLead).where(TeleCallLead.full_name == "Sara Joseph"))).scalar_one()
    assert sara.owner_user_id in (team["sureka"].id, team["riya"].id)
    assert sara.assignment_source == "store_tl"
    fu = (await db.execute(select(TeleLeadFollowup).where(TeleLeadFollowup.lead_id == sara.id))).scalar_one()
    assert fu.kind == "first_call" and fu.status == "open" and fu.owner_user_id == sara.owner_user_id
    assert result["crm"]["auto_assigned"] == 1 and result["crm"]["first_call_tasks"] == 1


@pytest.mark.asyncio
async def test_round_robin_spreads_new_leads(db, team, sheet):
    await tele_call_sync.sync_tele_call_leads(db)  # go-live with an empty sheet
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheet += [row(f"Lead {i}", f"98765000{i:02d}", stamp) for i in range(4)]
    await tele_call_sync.sync_tele_call_leads(db)
    owners = (await db.execute(select(TeleCallLead.owner_user_id))).scalars().all()
    assert owners.count(team["sureka"].id) == 2 and owners.count(team["riya"].id) == 2


@pytest.mark.asyncio
async def test_away_agents_are_skipped(db, team, sheet):
    await tele_call_sync.sync_tele_call_leads(db)
    team["riya"].available_for_leads = False
    await db.commit()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheet += [row(f"Lead {i}", f"98765000{i:02d}", stamp) for i in range(3)]
    await tele_call_sync.sync_tele_call_leads(db)
    owners = set((await db.execute(select(TeleCallLead.owner_user_id))).scalars().all())
    assert owners == {team["sureka"].id}


@pytest.mark.asyncio
async def test_name_fix_in_sheet_updates_same_lead(db, team, sheet):
    sheet.append(row("arjun", "+91 98765 00001", "2026-09-20 10:00"))
    await tele_call_sync.sync_tele_call_leads(db)
    sheet[0] = row("Arjun Mehta", "9876500001", "2026-09-20 10:00")
    await tele_call_sync.sync_tele_call_leads(db)
    names = (await db.execute(select(TeleCallLead.full_name))).scalars().all()
    assert names == ["Arjun Mehta"]


@pytest.mark.asyncio
async def test_app_edits_are_not_overwritten(db, team, sheet):
    sheet.append(row("Arjun", "9876500001", "2026-09-20 10:00", product="iPhone"))
    await tele_call_sync.sync_tele_call_leads(db)
    lead = (await db.execute(select(TeleCallLead))).scalar_one()
    lead.product = "iPhone 15 Pro"
    lead.edited_fields = ["product"]
    await db.commit()
    sheet[0] = row("Arjun", "9876500001", "2026-09-20 10:00", product="iPhone 15", status="Will Visit")
    await tele_call_sync.sync_tele_call_leads(db)
    await db.refresh(lead)
    assert lead.product == "iPhone 15 Pro"   # protected
    assert lead.status == "Will Visit"       # still follows the sheet


@pytest.mark.asyncio
async def test_status_update_in_sheet_completes_first_call(db, team, sheet):
    await tele_call_sync.sync_tele_call_leads(db)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheet.append(row("Sara", "9876500003", stamp))
    await tele_call_sync.sync_tele_call_leads(db)
    sheet[0] = row("Sara", "9876500003", stamp, status="Call Not Connected")
    await tele_call_sync.sync_tele_call_leads(db)
    fus = (await db.execute(select(TeleLeadFollowup).order_by(TeleLeadFollowup.id))).scalars().all()
    assert fus[0].kind == "first_call" and fus[0].status == "done"
    assert fus[1].kind == "call" and fus[1].status == "open"  # retry scheduled
    lead = (await db.execute(select(TeleCallLead))).scalar_one()
    assert lead.first_contact_at is not None and lead.stage == "contacting"


async def _tracked_lead(db, team, received):
    """A lead received at `received` (UTC) owned by Sureka with an open first-call task."""
    db.add(Setting(key="crm.go_live_at", value='"2026-01-01T00:00:00"'))
    lead = TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="sheet-kerala", full_name="Arjun",
                        phone="9876500001", status="", created_at=received, submitted_at=received,
                        owner_user_id=team["sureka"].id, assigned_at=received, assignment_source="auto",
                        stage="new", priority="warm")
    db.add(lead)
    await db.flush()
    db.add(TeleLeadFollowup(lead_id=lead.id, owner_user_id=team["sureka"].id, kind="first_call",
                            due_at=received + timedelta(minutes=5), status="open", created_at=received))
    await db.commit()
    return lead


@pytest.mark.asyncio
async def test_first_call_sla_alert_reassign_escalate(db, team):
    received = ist(2026, 9, 24, 10, 0)  # Thursday, working hours
    lead = await _tracked_lead(db, team, received)

    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=3))
    assert await count(db, CrmAlert) == 0

    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=6))
    await db.refresh(lead)
    alert = (await db.execute(select(CrmAlert))).scalar_one()
    assert alert.kind == "first_call_overdue" and alert.recipient_user_id == team["sureka"].id
    assert lead.is_urgent

    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=16))
    await db.refresh(lead)
    assert lead.owner_user_id == team["riya"].id and lead.reassign_count == 1
    fus = (await db.execute(select(TeleLeadFollowup).order_by(TeleLeadFollowup.id))).scalars().all()
    assert [(f.owner_user_id, f.status) for f in fus] == [
        (team["sureka"].id, "reassigned"), (team["riya"].id, "open")]
    # Sureka's alert resolved with her follow-up; Riya told the lead is hers
    await db.refresh(alert)
    assert alert.resolved_at is not None
    assert await count(db, CrmAlert, CrmAlert.kind == "reassigned_to_you",
                       CrmAlert.recipient_user_id == team["riya"].id) == 1

    # reassigned only once
    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=40))
    await db.refresh(lead)
    assert lead.owner_user_id == team["riya"].id and lead.reassign_count == 1

    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=61))
    await db.refresh(lead)
    assert lead.escalated_at is not None
    assert await count(db, CrmAlert, CrmAlert.kind == "first_call_escalated",
                       CrmAlert.recipient_user_id == team["tl"].id) == 1


@pytest.mark.asyncio
async def test_no_timers_run_outside_working_hours(db, team):
    received = ist(2026, 9, 24, 17, 58)  # 2 working minutes left on Thursday
    await _tracked_lead(db, team, received)
    await crm_automation.run_automation_tick(db, now=ist(2026, 9, 24, 23, 0))
    assert await count(db, CrmAlert) == 0          # only 2 working minutes have passed
    await crm_automation.run_automation_tick(db, now=ist(2026, 9, 25, 9, 4))
    assert await count(db, CrmAlert) == 1          # 6 working minutes


@pytest.mark.asyncio
async def test_logging_a_call_completes_task_and_schedules_next(db, team):
    received = ist(2026, 9, 24, 10, 0)
    lead = await _tracked_lead(db, team, received)
    automation = await get_automation(db)
    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=6))

    t = received + timedelta(minutes=7)
    res = await log_outcome(db, lead, team["sureka"], "busy", automation=automation, now=t,
                            actor_role="Telecaller")
    await db.commit()
    assert lead.status == "Call Not Connected" and lead.first_contact_at == t
    assert res["followup"].due_at == t + timedelta(minutes=45)
    assert await count(db, CrmAlert, CrmAlert.resolved_at.is_(None)) == 0  # alert cleared

    t2 = t + timedelta(minutes=46)
    res = await log_outcome(db, lead, team["sureka"], "busy", automation=automation, now=t2,
                            actor_role="Telecaller")
    await db.commit()
    assert res["followup"].due_at == ist(2026, 9, 25, 9, 0)  # 2 calls today → next day

    res = await log_outcome(db, lead, team["sureka"], "converted", automation=automation,
                            now=t2 + timedelta(minutes=1), sale_amount="12000", actor_role="Telecaller")
    await db.commit()
    assert res["followup"] is None and lead.stage == "converted" and lead.next_follow_up_at is None
    assert await count(db, TeleLeadFollowup, TeleLeadFollowup.status == "open") == 0


@pytest.mark.asyncio
async def test_metrics_attribute_misses_to_owner_at_the_time(db, team):
    received = ist(2026, 9, 24, 10, 0)
    lead = await _tracked_lead(db, team, received)
    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=16))  # → Riya
    automation = await get_automation(db)
    riya = team["riya"]
    await db.refresh(lead)
    await log_outcome(db, lead, riya, "will_visit", automation=automation,
                      now=received + timedelta(minutes=18), actor_role="Telecaller")
    await db.commit()

    agents = [{"id": team["sureka"].id, "name": "Sureka K"}, {"id": riya.id, "name": "Riya Menon"}]
    rows = await agent_report(db, agents, date(2026, 9, 21), date(2026, 9, 27),
                              now=received + timedelta(hours=1), automation=automation,
                              targets=await get_targets(db))
    by = {r["user_id"]: r for r in rows}
    s, r = by[team["sureka"].id], by[riya.id]
    assert (s["first_calls_total"], s["first_calls_on_time"]) == (1, 0)   # Sureka missed it
    assert (r["first_calls_total"], r["first_calls_on_time"]) == (1, 1)   # Riya called in time
    assert r["total_leads"] == 1 and r["will_visit"] == 1                 # lead now Riya's
    assert r["calls_logged"] == 1 and r["calls_connected_logged"] == 1


# ── appointment → sale matching (MCP sales report stubbed) ──
from app.models.models import Store, StoreMcpAlias, TeleAppointment  # noqa: E402
from app.services.crm.sale_match import run_lead_sale_match, run_sale_match  # noqa: E402


async def _appointment(db, team, day, phone="+91 98765 00001", name="Priya", hour=11):
    lead = TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="k", full_name=name, phone=phone, status="Will Visit",
                        stage="qualified", priority="warm", owner_user_id=team["sureka"].id,
                        created_at=ist(2026, 9, 20), submitted_at=ist(2026, 9, 20))
    db.add(lead)
    await db.flush()
    appt = TeleAppointment(lead_id=lead.id, scheduled_at=ist(day.year, day.month, day.day, hour, 0), purpose="Visit",
                           attendance="scheduled", source="app")
    db.add(appt)
    await db.commit()
    return lead, appt


def _fake_sales(rows_by_phone):
    calls = []

    async def fetch(start, end, phone):
        calls.append((start, end, phone))
        return [r for r in rows_by_phone.get(phone, []) if start.isoformat() <= r["iso"] <= end.isoformat()]
    return fetch, calls


def _sale(pid, iso, amount=6990.0, category="New Sale"):
    return {"id": pid, "date": iso, "iso": iso, "shop": "GuardX - Indiranagar", "category": category,
            "model": "IPHONE 17", "amount": amount, "discount": 0.0}


@pytest.mark.asyncio
async def test_sale_within_two_days_converts_the_lead(db, team):
    lead, appt = await _appointment(db, team, date(2026, 9, 25))
    fetch, calls = _fake_sales({"9876500001": [_sale(113001, "2026-09-26")]})
    stats = await run_sale_match(db, today=date(2026, 9, 26), fetch=fetch)
    await db.refresh(lead); await db.refresh(appt)
    assert stats["matched"] == 1
    assert calls == [(date(2026, 9, 25), date(2026, 9, 26), "9876500001")]
    assert lead.status == "Sale Conversion" and lead.stage == "converted" and lead.sale_amount == "6990"
    assert appt.sale_match_status == "matched" and appt.attendance == "attended" and appt.matched_purchase_id == "113001"
    assert await count(db, CrmAlert, CrmAlert.kind == "sale_matched") >= 1


@pytest.mark.asyncio
async def test_window_is_two_days_then_no_sale(db, team):
    lead, appt = await _appointment(db, team, date(2026, 9, 22))
    # a sale 3 days later is outside the window and must not match
    fetch, _ = _fake_sales({"9876500001": [_sale(113002, "2026-09-25")]})
    await run_sale_match(db, today=date(2026, 9, 24), fetch=fetch)       # day 2: still waiting
    await db.refresh(appt)
    assert appt.sale_match_status == "pending"
    await run_sale_match(db, today=date(2026, 9, 25), fetch=fetch)       # day 3: window closed
    await db.refresh(appt); await db.refresh(lead)
    assert appt.sale_match_status == "no_sale" and lead.status == "Will Visit"
    fu = (await db.execute(select(TeleLeadFollowup).where(TeleLeadFollowup.lead_id == lead.id))).scalar_one()
    assert "No sale found" in fu.reason
    # a later run leaves it alone
    stats = await run_sale_match(db, today=date(2026, 9, 26), fetch=fetch)
    assert stats["checked"] == 0


@pytest.mark.asyncio
async def test_replacements_and_reused_bills_do_not_match(db, team):
    lead1, a1 = await _appointment(db, team, date(2026, 9, 25), phone="9876500001", name="A")
    lead2, a2 = await _appointment(db, team, date(2026, 9, 25), phone="9876500001", name="B", hour=12)
    fetch, _ = _fake_sales({"9876500001": [_sale(1, "2026-09-25", 0.0, "Replacement"), _sale(2, "2026-09-25")]})
    stats = await run_sale_match(db, today=date(2026, 9, 25), fetch=fetch)
    await db.refresh(a1); await db.refresh(a2)
    assert stats["matched"] == 1
    assert {a1.sale_match_status, a2.sale_match_status} == {"matched", "pending"}  # bill #2 used once only


@pytest.mark.asyncio
async def test_sheet_appointment_dates_are_checked_and_bad_phones_skipped(db, team):
    db.add(TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="k", full_name="Sheet Appt", phone="9876500009",
                        status="Appointment", appointment_date="25/09/2026", owner_user_id=team["riya"].id,
                        created_at=ist(2026, 9, 20)))
    await _appointment(db, team, date(2026, 9, 25), phone="12345", name="Bad phone")
    fetch, _ = _fake_sales({"9876500009": [_sale(3, "2026-09-25", 4990.0)]})
    stats = await run_sale_match(db, today=date(2026, 9, 25), fetch=fetch)
    assert stats["sheet_appointments_added"] == 1 and stats["matched"] == 1 and stats["no_phone"] == 1


@pytest.mark.asyncio
async def test_matched_sale_links_the_store(db, team):
    store = Store(name="Bangalore Indiranagar", country="India", is_active=True, team_leader_id=team["tl"].id)
    db.add(store)
    await db.flush()
    db.add(StoreMcpAlias(store_id=store.id, mcp_shop_name="GuardX - Indiranagar"))
    lead, appt = await _appointment(db, team, date(2026, 9, 25))
    fetch, _ = _fake_sales({"9876500001": [_sale(113010, "2026-09-25")]})
    await run_sale_match(db, today=date(2026, 9, 25), fetch=fetch)
    await db.refresh(lead); await db.refresh(appt)
    assert appt.store_id == store.id and lead.store_id == store.id


@pytest.mark.asyncio
async def test_open_lead_without_appointment_who_bought_is_converted(db, team):
    store = Store(name="Bangalore Indiranagar", country="India", is_active=True, team_leader_id=team["tl"].id)
    db.add(store)
    await db.flush()
    db.add(StoreMcpAlias(store_id=store.id, mcp_shop_name="GuardX - Indiranagar"))
    walk_in = TeleCallLead(sheet_tl_name="Bangalore", spreadsheet_id="b", full_name="Walk", phone="9876500021",
                           status="Will Visit", created_at=ist(2026, 9, 20), submitted_at=ist(2026, 9, 20))
    early = TeleCallLead(sheet_tl_name="Bangalore", spreadsheet_id="b", full_name="Before", phone="9876500022",
                         status="", created_at=ist(2026, 9, 20), submitted_at=ist(2026, 9, 20))
    closed = TeleCallLead(sheet_tl_name="Bangalore", spreadsheet_id="b", full_name="NI", phone="9876500023",
                          status="Not Interested", created_at=ist(2026, 9, 20), submitted_at=ist(2026, 9, 20))
    db.add_all([walk_in, early, closed])
    await db.commit()
    fetch, calls = _fake_sales({"9876500021": [_sale(5, "2026-09-23")],
                                "9876500022": [_sale(6, "2026-09-18")],   # bought before the lead arrived
                                "9876500023": [_sale(7, "2026-09-23")]})
    stats = await run_lead_sale_match(db, today=date(2026, 9, 26), fetch=fetch)
    assert stats == {"leads_checked": 2, "leads_matched": 1, "errors": 0}   # "Not Interested" isn't searched
    await db.refresh(walk_in); await db.refresh(early)
    assert walk_in.status == "Sale Conversion" and walk_in.store_id == store.id and early.status == ""
    visit = (await db.execute(select(TeleAppointment).where(TeleAppointment.lead_id == walk_in.id))).scalar_one()
    assert (visit.source, visit.attendance, visit.store_id, visit.matched_purchase_id) == ("sale_match", "attended", store.id, "5")
    # a second run finds nothing new (the lead has a visit now)
    assert (await run_lead_sale_match(db, today=date(2026, 9, 26), fetch=fetch))["leads_matched"] == 0


# ── bill number on a lead → verified against the MCP bills ──
from app.models.models import McpBill  # noqa: E402
from app.services.crm.bill_verify import parse_bill_no, verify_bills  # noqa: E402


async def _bill_setup(db, team):
    store = Store(name="Kottakkal", country="India", is_active=True, team_leader_id=team["tl"].id)
    db.add(store)
    await db.flush()
    db.add(StoreMcpAlias(store_id=store.id, mcp_shop_name="FORTISAFE - Kottakkal"))
    db.add_all([
        McpBill(id=117180, date=date(2026, 9, 24), shop="FORTISAFE - Kottakkal", category="New Sale", amount=4041, paid=True),
        McpBill(id=117179, date=date(2026, 9, 24), shop="FORTISAFE - Kottakkal", category="Replacement", amount=0, paid=True),
        McpBill(id=110001, date=date(2026, 9, 10), shop="FORTISAFE - Kottakkal", category="New Sale", amount=3450, paid=True),
    ])

    def lead(name, bill, phone):
        l = TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="k", full_name=name, phone=phone, status="Will Visit",
                         lead_source="PM", sale_amount="5000", bill_no=bill,
                         created_at=ist(2026, 9, 20), submitted_at=ist(2026, 9, 20))
        db.add(l)
        return l
    return store, lead


def test_bill_numbers_are_read_however_they_are_typed():
    assert [parse_bill_no(t) for t in ("#117180", " Bill 117,180 ", "117180.0", "n/a", "", None)] == [117180, 117180, 117180, None, None, None]


@pytest.mark.asyncio
async def test_bill_number_verifies_the_sale_with_the_bills_own_figures(db, team):
    store, lead = await _bill_setup(db, team)
    a = lead("Asha", "#117180", "9876500031")
    await db.commit()
    assert (await verify_bills(db))["verified"] == 1
    await db.refresh(a)
    assert a.bill_status == "verified" and a.bill_note.startswith("#117180 · FORTISAFE - Kottakkal · ₹4,041")
    # the bill, not the typed 5000, is the amount; the lead lands on the bill's store
    assert (a.status, a.sale_amount, a.store_id) == ("Sale Conversion", "4041", store.id)
    visit = (await db.execute(select(TeleAppointment).where(TeleAppointment.lead_id == a.id))).scalar_one()
    assert (visit.source, visit.attendance, visit.matched_purchase_id, visit.store_id) == ("bill", "attended", "117180", store.id)
    # the sale counts on the bill's date, whenever the number was typed
    sold = (await db.execute(select(TeleLeadActivity).where(
        TeleLeadActivity.lead_id == a.id, TeleLeadActivity.new_value == "Sale Conversion"))).scalar_one()
    assert sold.created_at.date() == date(2026, 9, 24)
    assert (await verify_bills(db)) == {"verified": 0, "not_found": 0, "duplicate": 0, "check": 0}   # nothing left to check


@pytest.mark.asyncio
async def test_bill_checks_catch_wrong_numbers(db, team):
    _store, lead = await _bill_setup(db, team)
    first = lead("First", "117180", "9876500041")
    await db.commit()
    await verify_bills(db)
    second = lead("Second", "117180", "9876500042")        # same bill claimed again
    replacement = lead("Repl", "117179", "9876500043")     # a Replacement, not a sale
    early = lead("Early", "110001", "9876500044")          # bill dated before the lead arrived
    missing = lead("Missing", "999999", "9876500045")      # no such bill yet
    junk = lead("Junk", "paid cash", "9876500046")
    await db.commit()
    stats = await verify_bills(db)
    assert stats == {"verified": 0, "not_found": 1, "duplicate": 1, "check": 3}
    for l in (second, replacement, early, missing, junk):
        await db.refresh(l)
        assert l.status == "Will Visit"                     # none of them is converted
    assert second.bill_status == "duplicate" and "First" in second.bill_note
    assert "Replacement" in replacement.bill_note and "before this lead arrived" in early.bill_note
    # the bill reaches the sales report on a later sync: now it verifies
    db.add(McpBill(id=999999, date=date(2026, 9, 26), shop="FORTISAFE - Kottakkal", category="New Sale", amount=6291, paid=True))
    await db.commit()
    assert (await verify_bills(db))["verified"] == 1
    await db.refresh(missing)
    assert missing.status == "Sale Conversion" and missing.sale_amount == "6291"


@pytest.mark.asyncio
async def test_bill_number_typed_in_the_sheet_is_synced_and_verified(db, team, monkeypatch):
    await _bill_setup(db, team)
    await db.commit()
    row = {"lead_source": "GM", "created_time": "2026-09-20T10:00:00+05:30", "full_name": "Sheet Buyer", "phone": "9876500051",
           "email": "", "person_calling": "", "status": "Will Visit", "call_date": "", "appointment_date": "", "remarks": "",
           "sale_amount": "", "product": "", "bill_no": "117180"}
    monkeypatch.setattr(tele_call_sync, "TELE_CALL_SHEETS", [SHEET])
    monkeypatch.setattr(tele_call_sync, "_fetch_sheet_rows", lambda _sid, _tab=None: [dict(row)])
    out = await tele_call_sync.sync_tele_call_leads(db)
    assert out["crm"]["bills"]["verified"] == 1
    lead = (await db.execute(select(TeleCallLead).where(TeleCallLead.full_name == "Sheet Buyer"))).scalar_one()
    assert (lead.bill_no, lead.bill_status, lead.status, lead.sale_amount) == ("117180", "verified", "Sale Conversion", "4041")
    # the next sync still says "Will Visit" in the sheet: the verified sale stands
    await tele_call_sync.sync_tele_call_leads(db)
    await db.refresh(lead)
    assert lead.status == "Sale Conversion" and lead.bill_status == "verified"


# ── bill's customer mobile → lead, automatically ──
from app.services.crm.bill_verify import match_bills_by_mobile  # noqa: E402
from app.services.mcp_sync_service import _report_row, store_bills  # noqa: E402


@pytest.mark.asyncio
async def test_bill_with_customer_mobile_links_to_its_lead_automatically(db, team):
    store, lead = await _bill_setup(db, team)
    older = lead("Meena (old enquiry)", None, "+91 98765 00061")
    older.created_at = older.submitted_at = ist(2026, 9, 1)
    buyer = lead("Meena", None, "p:+919876500061")                      # same person, came back on 20 Sept
    late = lead("Late Lead", None, "9876500062")
    late.created_at = late.submitted_at = ist(2026, 9, 28)              # arrived after the bill
    await db.commit()
    rows = [
        {"purchase_id": 120001, "created_date": "2026-09-24", "shop_name": "FORTISAFE - Kottakkal", "purchase_category": "New Sale",
         "sale_amount": 6291.0, "payment_status": "paid", "mobile_number": "98765-00061", "customer_name": "Meena",
         "salesman": "Arun", "purchase_type": "Break Protection Care Plus", "is_care_plus_covered": True, "installation_status": "installed"},
        {"purchase_id": 120002, "created_date": "2026-09-24", "shop_name": "FORTISAFE - Kottakkal", "purchase_category": "New Sale",
         "sale_amount": 4990.0, "payment_status": "paid", "mobile_number": "9876500062"},
        {"purchase_id": 120003, "created_date": "2026-09-24", "shop_name": "FORTISAFE - Kottakkal", "purchase_category": "Replacement",
         "sale_amount": 0.0, "payment_status": "paid", "mobile_number": "9876500061"},
        {"purchase_id": 120004, "created_date": "2026-09-25", "shop_name": "FORTISAFE - Kottakkal", "purchase_category": "New Sale",
         "sale_amount": 3450.0, "payment_status": "pending", "mobile_number": None},
    ]
    assert await store_bills(db, 1, [_report_row(r) for r in rows]) == 4
    await db.commit()
    bill = (await db.execute(select(McpBill).where(McpBill.id == 120001))).scalar_one()
    assert (bill.mobile10, bill.salesman, bill.is_care_plus, bill.installation_status) == ("9876500061", "Arun", True, "installed")

    stats = await match_bills_by_mobile(db)
    assert stats == {"bills_with_mobile": 2, "matched": 1}               # the Replacement and the no-mobile bill aren't candidates
    for l in (older, buyer, late):
        await db.refresh(l)
    # the latest enquiry before the sale gets it; nobody typed anything
    assert (buyer.status, buyer.sale_amount, buyer.store_id, buyer.bill_no, buyer.bill_status) == (
        "Sale Conversion", "6291", store.id, "120001", "verified")
    assert buyer.bill_note.endswith("matched by mobile")
    assert older.status == "Will Visit" and late.status == "Will Visit"  # a lead that arrived after the bill doesn't claim it
    visit = (await db.execute(select(TeleAppointment).where(TeleAppointment.lead_id == buyer.id))).scalar_one()
    assert (visit.source, visit.matched_purchase_id) == ("phone", "120001")
    assert (await match_bills_by_mobile(db))["matched"] == 0            # runs every sync without double-counting


# ── store → team leader → telecaller ────────────────────────────────
@pytest.fixture
def thane_sheet(monkeypatch):
    rows: list[dict] = []
    monkeypatch.setattr(tele_call_sync, "TELE_CALL_SHEETS", [{"spreadsheet_id": "sheet-abd", "tl_name": "Thane"}])
    monkeypatch.setattr(tele_call_sync, "_fetch_sheet_rows", lambda _sid, _tab=None: [dict(r) for r in rows])
    return rows


async def _korum_team(db, with_telecaller: bool):
    """Korum Mall (the Thane tab's store) run by Abdullah; nobody is on the Thane tab."""
    from app.models.models import Store
    roles = {n: Role(name=n) for n in ("Telecaller", "Team Leader")}
    db.add_all(roles.values())
    await db.flush()
    abd = User(name="Abdullah", email="ab@x", password_hash="x", role_id=roles["Team Leader"].id)
    db.add(abd)
    await db.flush()
    db.add(Store(name="Mumbai - Korum Mall", country="India", is_active=True, team_leader_id=abd.id))
    team = {"tl": abd, "roles": roles}
    if with_telecaller:
        team["dilip"] = User(name="Dilip", email="d@x", password_hash="x", role_id=roles["Telecaller"].id,
                             team_leader_id=abd.id)
        db.add(team["dilip"])
    await db.commit()
    return team


@pytest.mark.asyncio
async def test_new_lead_goes_to_a_telecaller_of_the_stores_team_leader(db, thane_sheet):
    team = await _korum_team(db, with_telecaller=True)
    thane_sheet.append(row("Old", "9876500001", "2026-09-01T10:00:00+05:30"))
    await tele_call_sync.sync_tele_call_leads(db)                      # go-live
    thane_sheet.append(row("Ebrahim Sk", "9877000001", datetime.now().strftime("%Y-%m-%d %H:%M")))
    await tele_call_sync.sync_tele_call_leads(db)
    lead = (await db.execute(select(TeleCallLead).where(TeleCallLead.full_name == "Ebrahim Sk"))).scalar_one()
    assert lead.owner_user_id == team["dilip"].id and lead.assignment_source == "store_tl"
    assert await count(db, TeleLeadFollowup, TeleLeadFollowup.lead_id == lead.id) == 1   # first-call task


@pytest.mark.asyncio
async def test_team_leader_keeps_leads_until_the_team_has_a_telecaller(db, thane_sheet):
    team = await _korum_team(db, with_telecaller=False)
    thane_sheet += [row("Open Lead", "9877000002", "2026-10-15T10:00:00+05:30", status="will visit"),
                    row("Closed Lead", "9877000003", "2026-10-15T10:00:00+05:30", status="not interested")]
    await tele_call_sync.sync_tele_call_leads(db)
    leads = {l.full_name: l for l in (await db.execute(select(TeleCallLead))).scalars().all()}
    assert {l.owner_user_id for l in leads.values()} == {team["tl"].id}   # no telecaller: the team leader

    dilip = User(name="Dilip", email="d@x", password_hash="x", role_id=team["roles"]["Telecaller"].id,
                 team_leader_id=team["tl"].id)
    db.add(dilip)
    await db.commit()
    await tele_call_sync.sync_tele_call_leads(db)
    await db.refresh(leads["Open Lead"])
    await db.refresh(leads["Closed Lead"])
    assert leads["Open Lead"].owner_user_id == dilip.id        # handed on to the new telecaller
    assert leads["Closed Lead"].owner_user_id == team["tl"].id  # finished leads stay put


@pytest.mark.asyncio
async def test_person_calling_takes_over_once_they_have_a_login(db, thane_sheet):
    team = await _korum_team(db, with_telecaller=False)
    thane_sheet.append(row("Ebrahim Sk", "9877000001", "2026-10-15T10:00:00+05:30", person="SAMEER"))
    await tele_call_sync.sync_tele_call_leads(db)
    lead = (await db.execute(select(TeleCallLead))).scalar_one()
    assert lead.owner_user_id == team["tl"].id          # no "Sameer" login yet: the team leader holds it

    sameer = User(name="Sameer", email="sa@x", password_hash="x", role_id=team["roles"]["Telecaller"].id,
                  team_leader_id=team["tl"].id)
    db.add(sameer)
    await db.flush()
    db.add(TeleSheetAssignment(user_id=sameer.id, sheet_tl_name="Thane"))
    await db.commit()
    await tele_call_sync.sync_tele_call_leads(db)
    await db.refresh(lead)
    assert lead.owner_user_id == sameer.id and lead.assignment_source == "sheet"


# ── 15-minute rule, night queue, Meta / sheet duplicates ───────────
@pytest.mark.asyncio
async def test_one_telecaller_team_escalates_to_team_leader_at_15_minutes(db, team):
    """Nobody else to give it to: the lead stays with its telecaller and the
    team leader is escalated to at 15 minutes (not 60)."""
    team["riya"].available_for_leads = False
    received = ist(2026, 9, 24, 10, 0)
    lead = await _tracked_lead(db, team, received)
    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=14))
    await db.refresh(lead)
    assert lead.escalated_at is None
    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=16))
    await db.refresh(lead)
    assert lead.owner_user_id == team["sureka"].id and lead.reassign_count == 0
    assert lead.escalated_at is not None
    assert await count(db, CrmAlert, CrmAlert.kind == "first_call_escalated",
                       CrmAlert.recipient_user_id == team["tl"].id) == 1
    assert await count(db, CrmAlert, CrmAlert.kind == "no_agent_available") == 0
    await crm_automation.run_automation_tick(db, now=received + timedelta(minutes=61))
    assert await count(db, CrmAlert, CrmAlert.kind == "first_call_escalated") == 1  # once only


@pytest.mark.asyncio
async def test_night_leads_wait_and_are_handed_over_one_every_15_minutes(db, team, monkeypatch):
    from app.services.crm.night_queue import queue_lead, should_queue
    monkeypatch.setitem(DEFAULT_AUTOMATION, "night_queue", True)
    automation = await get_automation(db)
    night = ist(2026, 9, 24, 21, 0)  # Thursday 9 PM — hours are 09:00–18:00 in tests
    assert should_queue(night, automation) and not should_queue(ist(2026, 9, 25, 9, 0), automation)
    db.add(Setting(key="crm.go_live_at", value='"2026-01-01T00:00:00"'))
    leads = []
    for i, prio in enumerate(("warm", "hot")):
        lead = TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="", full_name=f"Night {i}", phone=f"98765011{i}0",
                            status="", stage="new", priority=prio, created_at=night + timedelta(minutes=i),
                            submitted_at=night + timedelta(minutes=i), source_channel="instagram")
        db.add(lead)
        await db.flush()
        queue_lead(db, lead, team["sureka"], now=night, automation=automation)
        leads.append(lead)
    await db.commit()
    warm, hot = leads

    await crm_automation.run_automation_tick(db, now=ist(2026, 9, 25, 8, 59))   # still closed
    assert await count(db, TeleCallLead, TeleCallLead.owner_user_id.isnot(None)) == 0
    await crm_automation.run_automation_tick(db, now=ist(2026, 9, 25, 9, 0))    # opening: one, hot first
    await db.refresh(hot)
    await db.refresh(warm)
    assert hot.owner_user_id == team["sureka"].id and warm.owner_user_id is None
    fu = (await db.execute(select(TeleLeadFollowup).where(TeleLeadFollowup.lead_id == hot.id))).scalar_one()
    assert fu.kind == "first_call" and fu.created_at == ist(2026, 9, 25, 9, 0)  # clock starts at hand-over
    await crm_automation.run_automation_tick(db, now=ist(2026, 9, 25, 9, 10))
    await db.refresh(warm)
    assert warm.owner_user_id is None                                            # 15-minute gap
    await crm_automation.run_automation_tick(db, now=ist(2026, 9, 25, 9, 15))
    await db.refresh(warm)
    assert warm.owner_user_id == team["sureka"].id
    # arrived 12 working hours "ago", but escalation counts from the hand-over
    await db.refresh(hot)
    assert hot.escalated_at is None


@pytest.mark.asyncio
async def test_meta_lead_and_its_sheet_copy_are_merged_into_one(db, team):
    from app.services.crm.store_rematch import rematch_stores
    at = ist(2026, 10, 9, 22, 55)
    webhook = TeleCallLead(sheet_tl_name="Kerala", spreadsheet_id="", full_name="Asha", phone="+91 98765 02222",
                           external_ref="meta:555", source_channel="instagram", status="", stage="new",
                           created_at=at, submitted_at=at)
    copy = TeleCallLead(sheet_tl_name="Trivandrum", spreadsheet_id="sheet-tvm", full_name="Asha K", phone="9876502222",
                        created_time="2026-10-09T12:25:15-05:00", source_channel="meta_sheet", status="Call back later",
                        stage="follow_up", created_at=at + timedelta(days=8), submitted_at=at + timedelta(minutes=1),
                        owner_user_id=team["riya"].id, assignment_source="sheet", person_calling="Riya")
    db.add_all([webhook, copy])
    await db.flush()
    db.add(TeleLeadActivity(lead_id=copy.id, type="call", user_id=team["riya"].id, notes="called", created_at=at))
    await db.commit()

    preview = await rematch_stores(db, team["admin"], apply=False)
    assert [(m["lead_id"], m["copy_id"]) for m in preview["merged"]] == [(webhook.id, copy.id)]
    assert await count(db, TeleCallLead) == 2  # preview writes nothing

    await rematch_stores(db, team["admin"], apply=True)
    leads = (await db.execute(select(TeleCallLead))).scalars().all()
    assert len(leads) == 1
    lead = leads[0]
    assert lead.id == webhook.id and lead.external_ref == "meta:555"
    # it is now the sheet row (the next sync updates it) and keeps the work done on the copy
    assert (lead.spreadsheet_id, lead.created_time, lead.full_name) == ("sheet-tvm", copy.created_time, "Asha K")
    assert lead.status == "Call back later" and lead.owner_user_id == team["riya"].id
    assert await count(db, TeleLeadActivity, TeleLeadActivity.lead_id == lead.id, TeleLeadActivity.notes == "called") == 1
