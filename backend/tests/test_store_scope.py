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
