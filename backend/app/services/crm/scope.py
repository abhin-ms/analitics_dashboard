"""Who can see which tele-call leads — one helper for every CRM endpoint.

Mirrors the rules already used by /tele-call-leads:
  * admin tier (SuperAdmin, Admin, CEO, COO, Regional Manager): everything
  * Team Leader / Telecaller: every lead on their assigned city sheets
    ("My leads" for a telecaller = leads they own)
  * Salesperson: leads where person_calling == their name (or they own)
  * anyone else: nothing
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import ADMIN_TIER_ROLES
from ...models.models import Role, TeleCallLead, TeleSheetAssignment, User

LEAD_WORKER_ROLES = {"Telecaller", "Team Leader", "Salesperson"}


@dataclass
class CrmScope:
    user: User
    role: str
    sheets: list[str] = field(default_factory=list)

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
        return self.is_admin or self.role in LEAD_WORKER_ROLES

    @property
    def can_reassign(self) -> bool:
        return self.is_admin or self.is_tl

    @property
    def can_edit_settings(self) -> bool:
        return self.role in {"SuperAdmin", "Admin"}


async def get_role_name(db: AsyncSession, user: User) -> str:
    return (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none() or ""


async def get_scope(db: AsyncSession, user: User) -> CrmScope:
    role = await get_role_name(db, user)
    sheets: list[str] = []
    if role in ("Team Leader", "Telecaller"):
        sheets = list((await db.execute(
            select(TeleSheetAssignment.sheet_tl_name).where(TeleSheetAssignment.user_id == user.id)
        )).scalars().all())
    return CrmScope(user=user, role=role, sheets=sheets)


def lead_filter(scope: CrmScope):
    """SQLAlchemy boolean clause restricting TeleCallLead rows to the scope."""
    if scope.is_admin:
        return TeleCallLead.id.isnot(None)
    if scope.role in ("Team Leader", "Telecaller"):
        if not scope.sheets:
            return false()
        return TeleCallLead.sheet_tl_name.in_(scope.sheets)
    if scope.is_salesperson:
        return or_(TeleCallLead.person_calling == scope.user.name,
                   TeleCallLead.owner_user_id == scope.user.id)
    return false()


def lead_in_scope(lead: TeleCallLead, scope: CrmScope) -> bool:
    if scope.is_admin:
        return True
    if scope.role in ("Team Leader", "Telecaller"):
        return lead.sheet_tl_name in scope.sheets
    if scope.is_salesperson:
        return lead.person_calling == scope.user.name or lead.owner_user_id == scope.user.id
    return False


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
