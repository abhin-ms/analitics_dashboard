"""A store owner's leads in the CRM: what they see and may do follows the
Leads ticks of their role (Roles & Permissions)."""
from datetime import datetime, timedelta

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import pytest_asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.v1.crm import require_scope  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.models import (  # noqa: E402
    Permission, Role, RolePermission, Store, TeleAppointment, TeleCallLead, TeleSheetAssignment, User,
    UserStoreAccess,
)
from app.services.crm.scope import get_scope, lead_filter, lead_in_scope  # noqa: E402


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def setup(db):
    roles = {n: Role(name=n) for n in ("Store Owner", "Team Leader")}
    db.add_all(roles.values())
    await db.flush()
    tl = User(name="Tara", email="t@x", password_hash="x", role_id=roles["Team Leader"].id)
    owner = User(name="Annu", email="a@x", password_hash="x", role_id=roles["Store Owner"].id)
    db.add_all([tl, owner])
    await db.flush()
    kochi = Store(name="Kochi", team_leader_id=tl.id, country="India")
    calicut = Store(name="Calicut", team_leader_id=tl.id, country="India")
    db.add_all([kochi, calicut])
    await db.flush()
    db.add(UserStoreAccess(user_id=owner.id, store_id=kochi.id))
    for sheet in ("Kochi", "Calicut", "Kerala"):  # "Kerala" covers several shops
        db.add(TeleSheetAssignment(user_id=tl.id, sheet_tl_name=sheet))
    now = datetime.utcnow()

    def lead(name, sheet, store=None):
        return TeleCallLead(sheet_tl_name=sheet, full_name=name, phone=name, status="", created_at=now,
                            submitted_at=now, store_id=store.id if store else None)
    leads = {"tagged": lead("tagged", "Website", kochi), "own_sheet": lead("own_sheet", "Kochi"),
             "shared_sheet": lead("shared_sheet", "Kerala"), "other_store": lead("other_store", "Kochi", calicut),
             "calicut_sheet": lead("calicut_sheet", "Calicut"), "booked": lead("booked", "Kerala")}
    db.add_all(leads.values())
    await db.flush()
    db.add(TeleAppointment(lead_id=leads["booked"].id, store_id=kochi.id, scheduled_at=now + timedelta(days=1)))
    await db.commit()
    return {"role": roles["Store Owner"], "owner": owner, "leads": leads}


async def tick(db, role, *actions):
    for a in actions:
        p = Permission(resource="leads", action=a)
        db.add(p)
        await db.flush()
        db.add(RolePermission(role_id=role.id, permission_id=p.id))
    await db.commit()


@pytest.mark.asyncio
async def test_store_owner_sees_their_stores_leads_by_their_ticks(db, setup):
    owner, role, leads = setup["owner"], setup["role"], setup["leads"]
    with pytest.raises(HTTPException) as e:  # no Leads tick: no CRM access
        await require_scope(db, owner)
    assert e.value.status_code == 403

    await tick(db, role, "view")
    scope = await require_scope(db, owner)
    assert scope.sheets == ["Kochi"]  # their store's own sheet, not the shared "Kerala" one
    seen = {l.full_name for l in (await db.execute(select(TeleCallLead).where(lead_filter(scope)))).scalars()}
    assert seen == {"tagged", "own_sheet", "booked"}
    assert all(lead_in_scope(l, scope) == (l.full_name in seen) for l in leads.values())
    assert not scope.can_reassign and not scope.can_edit_leads
    with pytest.raises(HTTPException) as e:  # view only: can't log a call
        await require_scope(db, owner, "edit")
    assert e.value.status_code == 403 and "view" in e.value.detail

    await tick(db, role, "edit")
    scope = await require_scope(db, owner, "edit")
    assert scope.can_edit_leads and not scope.can_reassign

    await tick(db, role, "manage")
    scope = await get_scope(db, owner)
    assert scope.can_reassign and scope.can("create")  # manage covers the rest


@pytest.mark.asyncio
async def test_store_staff_linked_to_one_store_sees_its_leads(db, setup):
    """A Store Staff account (its store set on the user, like the live "Kochi"
    account) gets the same store leads, by its own role's ticks."""
    staff_role = Role(name="Store Staff")
    db.add(staff_role)
    await db.flush()
    kochi_id = (await db.execute(select(Store.id).where(Store.name == "Kochi"))).scalar_one()
    staff = User(name="Kochi", email="k@x", password_hash="x", role_id=staff_role.id, store_id=kochi_id)
    db.add(staff)
    await db.commit()
    with pytest.raises(HTTPException):
        await require_scope(db, staff)
    await tick(db, staff_role, "view", "edit", "create", "manage")
    scope = await require_scope(db, staff, "edit")
    seen = {l.full_name for l in (await db.execute(select(TeleCallLead).where(lead_filter(scope)))).scalars()}
    assert seen == {"tagged", "own_sheet", "booked"} and scope.can_reassign


@pytest.mark.asyncio
async def test_telecaller_sees_only_their_own_stores_leads(db, setup):
    """Kochi's telecaller: Kochi's leads (tagged, on the Kochi sheet, booked
    into Kochi) and leads given to them — never Calicut's, nor the shared
    "Kerala" sheet's, though both stores share one team leader."""
    tc_role = Role(name="Telecaller")
    db.add(tc_role)
    await db.flush()
    stores = {s.name: s for s in (await db.execute(select(Store))).scalars().all()}
    tl = (await db.execute(select(User).where(User.name == "Tara"))).scalar_one()
    sudhi = User(name="Sudhi", email="su@x", password_hash="x", role_id=tc_role.id,
                 team_leader_id=tl.id, store_id=stores["Kochi"].id)
    db.add(sudhi)
    await db.flush()
    given = setup["leads"]["calicut_sheet"]  # a Calicut lead handed to Sudhi by hand: his to work
    given.owner_user_id = sudhi.id
    await db.commit()
    scope = await get_scope(db, sudhi)
    assert scope.store_bound and scope.store_ids == [stores["Kochi"].id]
    seen = {l.full_name for l in (await db.execute(select(TeleCallLead).where(lead_filter(scope)))).scalars()}
    assert seen == {"tagged", "own_sheet", "booked", "calicut_sheet"}
    assert "other_store" not in seen and "shared_sheet" not in seen
    assert all(lead_in_scope(l, scope) == (l.full_name in seen) for l in setup["leads"].values())


@pytest.mark.asyncio
async def test_a_lead_from_another_store_shows_its_store_name(db, setup):
    """A telecaller's store list holds only their own stores, so the lead
    carries its store's name — a Calicut lead held by Kochi's telecaller reads
    "Calicut", not "No store matched" (live: Wayanad lead with swalih)."""
    from app.api.v1.crm import lead_row, store_names
    leads = list(setup["leads"].values())
    stores = await store_names(db, leads)
    rows = {r["full_name"]: r["store_name"] for r in (lead_row(l, {}, stores=stores) for l in leads)}
    assert rows["other_store"] == "Calicut" and rows["tagged"] == "Kochi" and rows["own_sheet"] is None


async def _seen(db, user):
    scope = await get_scope(db, user)
    return scope, {l.full_name for l in (await db.execute(select(TeleCallLead).where(lead_filter(scope)))).scalars()}


ALL = {"tagged", "own_sheet", "shared_sheet", "other_store", "calicut_sheet", "booked"}


@pytest.mark.asyncio
async def test_admins_and_leads_tick_roles_see_every_store(db, setup):
    roles = {n: Role(name=n) for n in ("SuperAdmin", "Viewer")}
    db.add_all(roles.values())
    await db.flush()
    boss = User(name="Boss", email="b@x", password_hash="x", role_id=roles["SuperAdmin"].id)
    viewer = User(name="Vee", email="v@x", password_hash="x", role_id=roles["Viewer"].id)
    db.add_all([boss, viewer])
    await db.commit()
    assert (await _seen(db, boss))[1] == ALL                      # admin: every store

    with pytest.raises(HTTPException):                            # no Leads tick: nothing
        await require_scope(db, viewer)
    await tick(db, roles["Viewer"], "view")
    scope, seen = await _seen(db, viewer)
    assert seen == ALL and not scope.can_edit_leads and not scope.can_reassign
    with pytest.raises(HTTPException):                            # view only
        await require_scope(db, viewer, "edit")
    await tick(db, roles["Viewer"], "edit")
    assert (await require_scope(db, viewer, "edit")).can_edit_leads


@pytest.mark.asyncio
async def test_telecaller_with_two_assigned_stores_sees_both_and_nothing_else(db, setup):
    from app.services.crm.intake import store_telecallers
    tc_role = Role(name="Telecaller")
    db.add(tc_role)
    await db.flush()
    stores = {s.name: s for s in (await db.execute(select(Store))).scalars().all()}
    arjun = User(name="Arjun", email="ar@x", password_hash="x", role_id=tc_role.id, store_id=stores["Kochi"].id)
    db.add(arjun)
    await db.flush()
    db.add(UserStoreAccess(user_id=arjun.id, store_id=stores["Calicut"].id))  # "Also covers" Calicut
    await db.commit()
    scope, seen = await _seen(db, arjun)
    assert scope.store_ids == sorted([stores["Kochi"].id, stores["Calicut"].id])
    assert seen == ALL - {"shared_sheet"}                         # both stores, not the shared sheet
    assert [u.name for u in await store_telecallers(db, stores["Calicut"])] == ["Arjun"]


@pytest.mark.asyncio
async def test_fix_button_moves_other_store_leads_and_team_leaders_assign_unassigned(db, setup):
    """Leads a telecaller held for another store go to that store's own
    telecaller; one with no store goes back to Unassigned, where every team
    leader sees it and can give it out — a telecaller only for their stores."""
    from app.services.crm.scope import assignable_people, may_take
    from app.services.crm.store_rematch import rematch_stores
    tc_role = Role(name="Telecaller")
    admin_role = Role(name="SuperAdmin")
    db.add_all([tc_role, admin_role])
    await db.flush()
    stores = {s.name: s for s in (await db.execute(select(Store))).scalars().all()}
    tara = (await db.execute(select(User).where(User.name == "Tara"))).scalar_one()
    sudhi = User(name="Sudhi", email="su@x", password_hash="x", role_id=tc_role.id, team_leader_id=tara.id,
                 store_id=stores["Kochi"].id)
    swalih = User(name="Swalih", email="sw@x", password_hash="x", role_id=tc_role.id, team_leader_id=tara.id,
                  store_id=stores["Calicut"].id)
    boss = User(name="Boss", email="bo@x", password_hash="x", role_id=admin_role.id)
    db.add_all([sudhi, swalih, boss])
    await db.flush()
    leads = setup["leads"]
    unmatched = TeleCallLead(sheet_tl_name="Meta", full_name="unmatched", phone="u", status="",  # no store, no area
                             created_at=leads["tagged"].created_at, submitted_at=leads["tagged"].created_at)
    db.add(unmatched)
    await db.flush()
    leads["unmatched"] = unmatched
    for name in ("calicut_sheet", "shared_sheet", "own_sheet", "unmatched"):   # all given to Kochi's Sudhi
        leads[name].owner_user_id, leads[name].assignment_source = sudhi.id, "auto"
    await db.commit()

    preview = await rematch_stores(db, boss, apply=False, days=30)
    assert {(m["name"], m["to"]) for m in preview["moved"]} == {("calicut_sheet", "Swalih"),
                                                                ("unmatched", "Unassigned")}
    await rematch_stores(db, boss, apply=True, days=30)
    for l in leads.values():
        await db.refresh(l)
    assert leads["calicut_sheet"].owner_user_id == swalih.id and leads["calicut_sheet"].store_id == stores["Calicut"].id
    assert leads["unmatched"].owner_user_id is None                           # no store: back to Unassigned
    assert leads["own_sheet"].owner_user_id == sudhi.id                       # Kochi's own: stays
    assert leads["shared_sheet"].owner_user_id == sudhi.id                    # "Kerala" sheet, his own area: stays

    tl_scope = await get_scope(db, tara)
    tl_seen = {l.full_name for l in (await db.execute(select(TeleCallLead).where(lead_filter(tl_scope)))).scalars()}
    assert "unmatched" not in tl_seen          # no store, not her sheet: for the admins, not every team leader
    boss_seen = {l.full_name for l in (await db.execute(select(TeleCallLead).where(lead_filter(await get_scope(db, boss))))).scalars()}
    assert "unmatched" in boss_seen
    people = {p["name"]: p for p in await assignable_people(db, tl_scope)}
    assert {"Sudhi", "Swalih", "Tara"} <= set(people)
    assert may_take(people["Sudhi"], None) and may_take(people["Sudhi"], stores["Kochi"].id)
    assert not may_take(people["Sudhi"], stores["Calicut"].id)               # never another store's
    assert may_take(people["Tara"], stores["Calicut"].id)


@pytest.mark.asyncio
async def test_fix_reads_the_leads_own_store_text_before_its_sheet(db, setup):
    """An untagged lead on the shared "Kerala" sheet whose ad set names
    another shop ("Instant Forms - Calicut") goes to that shop's telecaller,
    not left with the Kochi telecaller it was given to."""
    from app.services.crm.store_rematch import rematch_stores
    tc_role, admin_role = Role(name="Telecaller"), Role(name="SuperAdmin")
    db.add_all([tc_role, admin_role])
    await db.flush()
    stores = {s.name: s for s in (await db.execute(select(Store))).scalars().all()}
    tara = (await db.execute(select(User).where(User.name == "Tara"))).scalar_one()
    sudhi = User(name="Sudhi", email="su@x", password_hash="x", role_id=tc_role.id, team_leader_id=tara.id,
                 store_id=stores["Kochi"].id)
    swalih = User(name="Swalih", email="sw@x", password_hash="x", role_id=tc_role.id, team_leader_id=tara.id,
                  store_id=stores["Calicut"].id)
    boss = User(name="Boss", email="bo@x", password_hash="x", role_id=admin_role.id)
    db.add_all([sudhi, swalih, boss])
    await db.flush()
    lead = setup["leads"]["shared_sheet"]
    lead.owner_user_id, lead.assignment_source = sudhi.id, "auto"
    lead.source_channel, lead.preferred_store_text = "facebook", "Instant Forms - Calicut"
    await db.commit()
    await rematch_stores(db, boss, apply=True, days=30)
    await db.refresh(lead)
    assert lead.owner_user_id == swalih.id and lead.store_id == stores["Calicut"].id


@pytest.mark.asyncio
async def test_leads_update_page_shows_a_telecaller_only_their_store(db, setup):
    """Leads Update follows the same rules as the Leads page: Kochi's
    telecaller — even with the shared "Kerala" sheet assigned — sees and may
    edit Kochi's leads and the ones given to them, grouped under Kochi; never
    Calicut's or the rest of the Kerala sheet."""
    from app.api.v1.tele_call_leads import LeadUpdate, get_tele_call_leads, update_lead
    tc_role = Role(name="Telecaller")
    db.add(tc_role)
    await db.flush()
    stores = {s.name: s for s in (await db.execute(select(Store))).scalars().all()}
    tara = (await db.execute(select(User).where(User.name == "Tara"))).scalar_one()
    sudhi = User(name="Sudhi", email="su@x", password_hash="x", role_id=tc_role.id,
                 team_leader_id=tara.id, store_id=stores["Kochi"].id)
    db.add(sudhi)
    await db.flush()
    db.add(TeleSheetAssignment(user_id=sudhi.id, sheet_tl_name="Kerala"))  # used to open the whole sheet
    await db.commit()

    async def page(user, group_by="store"):
        return await get_tele_call_leads(tl_name="", status="", person_calling="", group_by=group_by, db=db, user=user)

    data = await page(sudhi)
    seen = {l["full_name"] for g in data["tl_groups"].values() for l in g["leads"]}
    assert seen == {"tagged", "own_sheet", "booked"}
    assert set(data["tl_groups"]) == {"Kochi"}  # own-sheet and booked leads are Kochi's too

    leads = setup["leads"]
    r = await update_lead(leads["tagged"].id, LeadUpdate(status="Will Visit"), db=db, user=sudhi)
    assert r["lead"]["status"] == "Will Visit"
    for other in ("other_store", "shared_sheet"):
        with pytest.raises(HTTPException) as e:
            await update_lead(leads[other].id, LeadUpdate(status="Will Visit"), db=db, user=sudhi)
        assert e.value.status_code == 403

    # the team leader: both stores and their sheets, by store or by sheet
    tl_seen = {l["full_name"] for g in (await page(tara, "sheet"))["tl_groups"].values() for l in g["leads"]}
    assert tl_seen == set(leads)


@pytest.mark.asyncio
async def test_team_telecalling_per_telecaller_and_source(db, setup):
    """A team leader's telecalling for a period: each telecaller's leads,
    attended / not attended, calls made (a sheet update counts for the
    lead's owner) — overall and per source; unassigned store leads too;
    other teams and other periods left out."""
    from app.models.models import TeleLeadActivity
    from app.services.crm.metrics import period_bounds
    from app.services.crm.team_telecalling import team_telecalling
    from datetime import date
    tc_role = Role(name="Telecaller")
    db.add(tc_role)
    await db.flush()
    stores = {s.name: s for s in (await db.execute(select(Store))).scalars().all()}
    tara = (await db.execute(select(User).where(User.name == "Tara"))).scalar_one()
    sudhi = User(name="Sudhi", email="su@x", password_hash="x", role_id=tc_role.id, team_leader_id=tara.id,
                 store_id=stores["Kochi"].id)
    swalih = User(name="Swalih", email="sw@x", password_hash="x", role_id=tc_role.id, store_id=stores["Calicut"].id)
    other = User(name="Other", email="ot@x", password_hash="x", role_id=tc_role.id)  # another team
    db.add_all([sudhi, swalih, other])
    await db.flush()
    day = datetime(2026, 10, 20, 6, 0)  # 20 Oct, 11:30 IST

    def lead(name, src, owner, status="", store=None, at=day):
        return TeleCallLead(sheet_tl_name="Kochi", full_name=name, phone=name, status=status, source_channel=src,
                            owner_user_id=owner.id if owner else None, store_id=store.id if store else None,
                            created_at=at, submitted_at=at)
    leads = [lead("w1", "website", sudhi, "Will Visit"), lead("w2", "website", sudhi),
             lead("f1", "facebook", sudhi, "Call Not Connected"), lead("i1", "instagram", swalih),
             lead("u1", "instagram", None, store=stores["Kochi"]),          # unassigned, Tara's store
             lead("x1", "facebook", other, "Will Visit"),                    # another team
             lead("old", "facebook", sudhi, "Will Visit", at=datetime(2026, 10, 1, 6, 0))]  # earlier: not a lead of the period
    db.add_all(leads)
    await db.flush()
    by = {l.full_name: l for l in leads}
    db.add_all([TeleLeadActivity(lead_id=by["w1"].id, type="call", user_id=sudhi.id, created_at=day),
                TeleLeadActivity(lead_id=by["f1"].id, type="status_change", user_id=None, created_at=day),   # sheet: Sudhi's
                TeleLeadActivity(lead_id=by["old"].id, type="status_change", user_id=None, created_at=day),  # follow-up of an older lead
                TeleLeadActivity(lead_id=by["x1"].id, type="call", user_id=other.id, created_at=day)])
    await db.commit()

    s, e = period_bounds(date(2026, 10, 20), date(2026, 10, 20))
    r = await team_telecalling(db, tara, s, e)
    rows = {x["name"]: x for x in r["telecallers"]}
    assert set(rows) == {"Sudhi", "Swalih", "Unassigned"}                       # not "Other"
    su = rows["Sudhi"]
    assert (su["leads"], su["attended"], su["not_attended"], su["attended_pct"], su["calls"]) == (3, 2, 1, 67, 3)
    assert su["by_source"]["website"] == {"leads": 2, "attended": 1, "calls": 1, "not_attended": 1}
    assert su["by_source"]["facebook"] == {"leads": 1, "attended": 1, "calls": 2, "not_attended": 0}
    assert rows["Swalih"]["store"] == "Calicut" and rows["Swalih"]["not_attended"] == 1
    assert rows["Unassigned"]["leads"] == 1
    assert r["total"]["leads"] == 5 and r["total"]["calls"] == 3
    assert [x["label"] for x in r["sources"]] == ["Website", "Facebook", "Instagram"]
