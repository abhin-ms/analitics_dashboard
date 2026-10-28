"""Who can see which tele-call leads — one helper for every CRM endpoint.

Mirrors the rules already used by /tele-call-leads:
  * admin tier (SuperAdmin, Admin, CEO, COO, Regional Manager): everything
  * any other role with Leads → View ticked (e.g. Viewer): everything too,
    working the leads only with its Edit / Manage ticks
  * Team Leader: every lead on their city sheets and of their stores, and
    every unassigned lead (to pick up and assign)
  * Telecaller with assigned store(s): those stores' leads (tagged with it, on
    its own city sheet, booked into it) and leads given to them — never
    another store's; without a store: their city sheets and team's stores
    ("My leads" for a telecaller = leads they own)
  * Salesperson: leads where person_calling == their name (or they own)
  * Store Owner / Store Staff (with Leads → View ticked for the role): their stores'
    leads — tagged with the store, on the store's own city sheet, or with an
    appointment there; Edit / Manage ticks let them work and reassign them
  * anyone else: nothing
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import ADMIN_TIER_ROLES
from ...models.models import Role, Store, TeleCallLead, TeleSheetAssignment, User

LEAD_WORKER_ROLES = {"Telecaller", "Team Leader", "Salesperson"}
STORE_ROLES = {"Store Owner", "Store Staff"}


@dataclass
class CrmScope:
    user: User
    role: str
    sheets: list[str] = field(default_factory=list)
    # Stores whose leads this person also sees (website leads are routed by
    # store → team leader, not by city sheet): a team leader's own stores; a
    # telecaller's team leader's stores; a store owner's own stores.
    store_ids: list[int] = field(default_factory=list)
    # Store owner: leads booked into their stores, and their role's ticks
    appointment_lead_ids: set[int] = field(default_factory=set)
    perms: set[tuple[str, str]] = field(default_factory=set)
    # A telecaller with their own store (Settings → Users) sees that store's
    # leads only — plus any lead given to them — not their team leader's other stores
    store_bound: bool = False
    # Any other role with Leads → View ticked (e.g. Viewer): every store's
    # leads, like admins; Edit / Manage ticks decide what else it may do
    global_view: bool = False

    @property
    def is_store(self) -> bool:
        return self.role in STORE_ROLES

    def can(self, action: str) -> bool:
        """A tick on Leads in Roles & Permissions (manage implies the rest)."""
        return ("leads", action) in self.perms or ("leads", "manage") in self.perms

    @property
    def can_edit_leads(self) -> bool:
        """Log calls, change status, book appointments."""
        return not (self.is_store or self.global_view) or self.can("edit")

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_TIER_ROLES

    @property
    def is_tl(self) -> bool:
        return self.role == "Team Leader"

    @property
    def is_telecaller(self) -> bool:
        return self.role == "Telecaller"

    @property
    def is_salesperson(self) -> bool:
        return self.role == "Salesperson"

    @property
    def has_access(self) -> bool:
        return (self.is_admin or self.role in LEAD_WORKER_ROLES
                or ((self.is_store or self.global_view) and self.can("view")))

    @property
    def can_reassign(self) -> bool:
        return self.is_admin or self.is_tl or ((self.is_store or self.global_view) and self.can("manage"))

    @property
    def can_edit_settings(self) -> bool:
        return self.role in {"SuperAdmin", "Admin"}


async def get_role_name(db: AsyncSession, user: User) -> str:
    return (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none() or ""


async def get_scope(db: AsyncSession, user: User) -> CrmScope:
    role = await get_role_name(db, user)
    sheets: list[str] = []
    store_ids: list[int] = []
    if role in ("Team Leader", "Telecaller"):
        sheets = list((await db.execute(
            select(TeleSheetAssignment.sheet_tl_name).where(TeleSheetAssignment.user_id == user.id)
        )).scalars().all())
        tl_id = user.id if role == "Team Leader" else user.team_leader_id
        if tl_id:
            from ...models.models import Store
            store_ids = list((await db.execute(
                select(Store.id).where(Store.team_leader_id == tl_id)
            )).scalars().all())
    if role in STORE_ROLES:
        return await _store_scope(db, user, role)
    if role == "Telecaller":
        assigned = await assigned_store_ids(db, user)
        if assigned:
            own_sheets, appt = await _store_view(db, assigned)
            return CrmScope(user=user, role=role, sheets=own_sheets, store_ids=sorted(assigned),
                            appointment_lead_ids=appt, store_bound=True)
    if not (role in ADMIN_TIER_ROLES or role in LEAD_WORKER_ROLES):
        from ...core.deps import get_user_permissions
        perms = {(p["resource"], p["action"]) for p in await get_user_permissions(user, db)}
        return CrmScope(user=user, role=role, perms=perms, global_view=("leads", "view") in perms
                        or ("leads", "manage") in perms)
    return CrmScope(user=user, role=role, sheets=sheets, store_ids=store_ids)


async def assigned_store_ids(db: AsyncSession, user: User) -> set[int]:
    """The stores a person is assigned to: their own store and any further
    stores ticked for them (Settings → Users)."""
    from ...models.models import UserStoreAccess
    ids = set((await db.execute(
        select(UserStoreAccess.store_id).where(UserStoreAccess.user_id == user.id))).scalars().all())
    if user.store_id:
        ids.add(user.store_id)
    return ids


async def _store_view(db: AsyncSession, store_ids: set[int]) -> tuple[list[str], set[int]]:
    """(the city sheets that are one of these shops' own sheet — a sheet
    covering several shops, like "Kerala", is not —, ids of leads with an
    appointment at these stores)."""
    from ...models.models import Store, TeleAppointment
    from ..store_portfolio import shop_of, shop_of_sheet
    names = (await db.execute(select(Store.name).where(Store.id.in_(store_ids or {-1})))).scalars().all()
    shops = {shop_of(n) for n in names} - {None}
    all_sheets = set((await db.execute(select(TeleSheetAssignment.sheet_tl_name).distinct())).scalars().all())
    try:
        from ..tele_call_sync import TELE_CALL_SHEETS
        all_sheets |= {s["tl_name"] for s in TELE_CALL_SHEETS}
    except Exception:  # the sheet list is optional here
        pass
    sheets = sorted(s for s in all_sheets if s and shop_of_sheet(s) in shops)
    appt = set((await db.execute(select(TeleAppointment.lead_id).where(
        TeleAppointment.store_id.in_(store_ids or {-1})))).scalars().all())
    return sheets, appt


async def _store_scope(db: AsyncSession, user: User, role: str) -> CrmScope:
    """A store owner: their stores, the city sheets that are one of those
    shops' own sheet (a sheet covering several shops, like "Kerala", is not),
    leads with an appointment at their stores, and their role's Leads ticks."""
    from ...core.deps import get_user_permissions
    store_ids = await assigned_store_ids(db, user)
    sheets, appt = await _store_view(db, store_ids)
    perms = {(p["resource"], p["action"]) for p in await get_user_permissions(user, db)}
    return CrmScope(user=user, role=role, sheets=sheets, store_ids=sorted(store_ids),
                    appointment_lead_ids=appt, perms=perms)


def lead_filter(scope: CrmScope):
    """SQLAlchemy boolean clause restricting TeleCallLead rows to the scope."""
    if scope.is_admin or scope.global_view:
        return TeleCallLead.id.isnot(None)
    if scope.is_store or scope.store_bound:
        clauses = [TeleCallLead.store_id.in_(scope.store_ids or [-1])]
        if scope.store_bound:  # a lead given to the telecaller is theirs to work
            clauses.append(TeleCallLead.owner_user_id == scope.user.id)
        if scope.sheets:  # the store's own city sheet, unless the lead names another store
            clauses.append(TeleCallLead.sheet_tl_name.in_(scope.sheets) & TeleCallLead.store_id.is_(None))
        if scope.appointment_lead_ids:
            clauses.append(TeleCallLead.id.in_(scope.appointment_lead_ids))
        return or_(*clauses)
    if scope.role in ("Team Leader", "Telecaller"):
        clauses = [TeleCallLead.owner_user_id == scope.user.id]
        if scope.sheets:
            clauses.append(TeleCallLead.sheet_tl_name.in_(scope.sheets))
        if scope.store_ids:
            clauses.append(TeleCallLead.store_id.in_(scope.store_ids))
        if scope.is_tl:  # every unassigned lead, for a team leader to pick up and assign
            clauses.append(TeleCallLead.owner_user_id.is_(None))
        return or_(*clauses)
    if scope.is_salesperson:
        return or_(TeleCallLead.person_calling == scope.user.name,
                   TeleCallLead.owner_user_id == scope.user.id)
    return false()


def lead_in_scope(lead: TeleCallLead, scope: CrmScope) -> bool:
    if scope.is_admin or scope.global_view:
        return True
    if scope.store_bound and lead.owner_user_id == scope.user.id:
        return True
    if scope.is_store or scope.store_bound:
        return (lead.store_id in scope.store_ids
                or (lead.store_id is None and lead.sheet_tl_name in scope.sheets)
                or lead.id in scope.appointment_lead_ids)
    if scope.role in ("Team Leader", "Telecaller"):
        return (lead.sheet_tl_name in scope.sheets or lead.owner_user_id == scope.user.id
                or (lead.store_id is not None and lead.store_id in scope.store_ids)
                or (scope.is_tl and lead.owner_user_id is None))
    if scope.is_salesperson:
        return lead.person_calling == scope.user.name or lead.owner_user_id == scope.user.id
    return False


ASSIGNABLE_ROLES = {"Telecaller", "Team Leader", "Salesperson"}


async def assignable_people(db: AsyncSession, scope: CrmScope) -> list[dict]:
    """Who this person may hand leads to, with the stores each covers:
    admins (and Leads-manage roles) anyone who works leads; a team leader
    themself, the telecallers reporting to them or assigned to their stores,
    and the people on their city sheets."""
    from ...models.models import UserStoreAccess
    q = (select(User, Role.name).join(Role, Role.id == User.role_id)
         .where(Role.name.in_(ASSIGNABLE_ROLES), User.is_active == True))  # noqa: E712
    users = (await db.execute(q)).all()
    extra: dict[int, set[int]] = {}
    for uid, sid in (await db.execute(select(UserStoreAccess.user_id, UserStoreAccess.store_id))).all():
        extra.setdefault(uid, set()).add(sid)
    sheets_of: dict[int, list[str]] = {}
    for m in await sheet_members(db, None):
        sheets_of[m["id"]] = m["sheets"]
    tl_store_rows = (await db.execute(select(Store.id, Store.team_leader_id).where(Store.is_active == True))).all()  # noqa: E712
    tl_stores: dict[int, set[int]] = {}
    for sid, tl in tl_store_rows:
        tl_stores.setdefault(tl, set()).add(sid)

    def stores_of(u: User, role: str) -> list[int]:
        if role == "Team Leader":
            return sorted(tl_stores.get(u.id, set()))
        return sorted(({u.store_id} if u.store_id else set()) | extra.get(u.id, set()))

    out = []
    for u, role in users:
        person = {"id": u.id, "name": u.name, "role": role, "sheets": sheets_of.get(u.id, []),
                  "stores": stores_of(u, role), "team_leader_id": u.team_leader_id,
                  "available": u.available_for_leads is not False}
        if scope.is_admin or (scope.global_view and scope.can("manage")):
            out.append(person)
        elif scope.is_tl and (u.id == scope.user.id or u.team_leader_id == scope.user.id
                              or set(person["stores"]) & set(scope.store_ids)
                              or set(person["sheets"]) & set(scope.sheets)):
            out.append(person)
    return sorted(out, key=lambda p: p["name"].lower())


def may_take(person: dict, store_id: int | None) -> bool:
    """A telecaller only takes leads of the stores they cover; a lead whose
    store isn't known can go to anyone, and team leaders take any."""
    return person["role"] != "Telecaller" or store_id is None or store_id in person["stores"]


async def sheet_members(db: AsyncSession, sheet_names: list[str] | None = None,
                        roles: set[str] | None = None, only_active: bool = True) -> list[dict]:
    """Users assigned to the given city sheets (all sheets if None), with
    their role and sheets. Used for owner matching, round-robin and team lists."""
    q = (
        select(User, Role.name, TeleSheetAssignment.sheet_tl_name)
        .join(TeleSheetAssignment, TeleSheetAssignment.user_id == User.id)
        .join(Role, Role.id == User.role_id)
    )
    if sheet_names is not None:
        if not sheet_names:
            return []
        q = q.where(TeleSheetAssignment.sheet_tl_name.in_(sheet_names))
    if roles:
        q = q.where(Role.name.in_(roles))
    if only_active:
        q = q.where(User.is_active == True)  # noqa: E712
    rows = (await db.execute(q)).all()
    by_id: dict[int, dict] = {}
    for u, role_name, sheet in rows:
        entry = by_id.setdefault(u.id, {
            "id": u.id, "name": u.name, "email": u.email, "role": role_name,
            "available": u.available_for_leads is not False,
            "team_leader_id": u.team_leader_id, "sheets": [],
        })
        if sheet not in entry["sheets"]:
            entry["sheets"].append(sheet)
    return sorted(by_id.values(), key=lambda e: e["name"].lower())


async def visible_agents(db: AsyncSession, scope: CrmScope) -> list[dict]:
    """People whose performance this scope may see: a telecaller sees only
    themselves, a team leader their city sheets' telecallers (plus anyone who
    reports to them), admins everyone on any sheet."""
    if scope.is_telecaller or scope.is_salesperson:
        return [{"id": scope.user.id, "name": scope.user.name, "role": scope.role,
                 "sheets": scope.sheets, "available": scope.user.available_for_leads is not False}]
    if scope.is_tl:
        members = await sheet_members(db, scope.sheets, roles={"Telecaller", "Salesperson"})
        ids = {m["id"] for m in members}
        direct = (await db.execute(
            select(User, Role.name).join(Role, Role.id == User.role_id)
            .where(User.team_leader_id == scope.user.id, User.is_active == True)  # noqa: E712
        )).all()
        for u, role_name in direct:
            if u.id not in ids:
                members.append({"id": u.id, "name": u.name, "email": u.email, "role": role_name,
                                "available": u.available_for_leads is not False,
                                "team_leader_id": u.team_leader_id, "sheets": []})
        return sorted(members, key=lambda e: e["name"].lower())
    if scope.is_admin:
        return await sheet_members(db, None, roles={"Telecaller", "Salesperson", "Team Leader"})
    return []
