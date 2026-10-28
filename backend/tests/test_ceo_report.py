"""The CEO report ranks people: each telecaller's leads, % attended, calls
made, first-call time and sales; each team leader's whole team — best to
worst — and renders it as a PDF."""
from datetime import datetime, timedelta

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")
pytest.importorskip("fpdf")

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.models.models import Role, TeleCallLead, TeleLeadActivity, User  # noqa: E402
from app.services.crm.ceo_report import _highlights, build_report, render_pdf  # noqa: E402
from app.services.crm.timeutil import from_ist  # noqa: E402

NOW = from_ist(datetime(2026, 10, 28, 20, 0))  # the 8 PM report


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_report_ranks_telecallers_and_team_leaders(db):
    tc, tl = Role(name="Telecaller"), Role(name="Team Leader")
    db.add_all([tc, tl])
    await db.flush()
    tara, mili = (User(name=n, email=f"{n}@x", password_hash="x", role_id=tl.id) for n in ("Tara", "Mili"))
    db.add_all([tara, mili])
    await db.flush()
    ann, bob, cat = (User(name=n, email=f"{n}@x", password_hash="x", role_id=tc.id, team_leader_id=t.id)
                     for n, t in (("Ann", tara), ("Bob", tara), ("Cat", mili)))
    db.add_all([ann, bob, cat])
    await db.flush()
    at = NOW - timedelta(hours=3)

    def lead(owner, attended, **kw):
        return TeleCallLead(sheet_tl_name="Kochi", full_name="c", phone="p", created_at=at, owner_user_id=owner.id,
                            status="Interested" if attended else "",
                            first_contact_at=at + timedelta(minutes=5) if attended else None, **kw)
    leads = [lead(ann, True, stage="converted"), lead(ann, True),          # Ann 2/2
             lead(bob, True), lead(bob, False),                             # Bob 1/2
             lead(cat, False), lead(cat, False),                            # Cat 0/2
             TeleCallLead(sheet_tl_name="Kochi", full_name="c", phone="p", created_at=at, status="")]  # unassigned
    db.add_all(leads)
    await db.flush()
    old = [TeleCallLead(sheet_tl_name="Kochi", full_name="o", phone="o", created_at=NOW - timedelta(days=5),
                        owner_user_id=bob.id, status="Follow up") for _ in range(3)]  # follow-ups from last week
    db.add_all(old)
    await db.flush()

    def act(lead_, who, type_="call", when=at):
        return TeleLeadActivity(lead_id=lead_.id, user_id=who.id if who else None, type=type_, created_at=when)
    db.add_all([act(leads[0], ann), act(leads[0], ann), act(leads[1], ann),  # Ann: 2 leads (one called twice)
                act(leads[2], bob), *(act(o, None, "status_change") for o in old),  # Bob: 1 + 3 updated on the sheet
                act(leads[2], bob, "note"), act(leads[3], bob, when=NOW - timedelta(days=2)),  # not counted
                act(leads[4], None, "status_change")])  # Cat: 1, on the sheet
    await db.commit()

    r = await build_report(db, NOW)
    rows = {t["name"]: t for t in r["telecallers"]}
    assert [t["name"] for t in r["telecallers"]] == ["Ann", "Bob", "Cat"]  # by % attended
    assert rows["Ann"] == {**rows["Ann"], "leads": 2, "attended": 2, "missed": 0, "attended_pct": 100,
                           "calls": 2, "converted": 1, "avg_first_call": 5, "team_leader": "Tara"}
    assert rows["Bob"]["calls"] == 4  # sheet updates count for the owner; notes and older calls don't
    assert rows["Cat"]["calls"] == 1
    assert rows["Cat"]["attended_pct"] == 0 and rows["Cat"]["avg_first_call"] is None
    teams = {t["name"]: t for t in r["team_leaders"]}
    assert [t["name"] for t in r["team_leaders"]] == ["Tara", "Mili"]
    assert teams["Tara"]["leads"] == 4 and teams["Tara"]["attended_pct"] == 75 and teams["Tara"]["calls"] == 6
    assert r["calls_made"] == 7 and r["total"]["received"] == 7  # the unassigned lead counts, isn't ranked

    cards = {label: name for label, name, _, _ in _highlights(r)}
    assert cards == {"BEST TELECALLER": "Ann", "NEEDS ATTENTION": "Cat", "BEST TEAM LEADER": "Tara",
                     "WEAKEST TEAM LEADER": "Mili", "MOST CALLS": "Bob", "FEWEST CALLS": "Cat"}
    assert render_pdf(r).startswith(b"%PDF")


def test_the_8_pm_report_covers_the_day_ending_not_the_new_one():
    from app.services.crm.ceo_report import report_window
    for minutes_late in (0, 1, 25):
        start, _ = report_window(NOW + timedelta(minutes=minutes_late))
        assert start == from_ist(datetime(2026, 10, 27, 20, 0))
    assert report_window(from_ist(datetime(2026, 10, 28, 13, 0)))[0] == from_ist(datetime(2026, 10, 27, 20, 0))
    assert report_window(from_ist(datetime(2026, 10, 28, 21, 0)))[0] == from_ist(datetime(2026, 10, 28, 20, 0))


@pytest.mark.asyncio
async def test_empty_day_still_renders(db):
    r = await build_report(db, NOW)
    assert r["telecallers"] == [] and r["team_leaders"] == [] and _highlights(r) == []
    assert render_pdf(r).startswith(b"%PDF")
