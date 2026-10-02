"""Live "new lead" notifications: a bell entry, a popup and a sound for the
people who should know a lead just arrived.

  * assigned lead → its owner ("assigned to you"), plus the rest of the
    branch team and the branch's team leader ("new lead for <branch>")
  * unassigned lead → every telecaller and every admin

Branch team: for a store-routed lead (website, Meta webhook) the store's
team leader and their telecallers; for a city-sheet lead the people on that
city sheet. Rows are written in the caller's transaction; push them with
emit_notifications() after the commit.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import CrmNotification, Role, Store, TeleCallLead, User
from .engine import admin_ids, user_names
from .scope import sheet_members
from .timeutil import iso_utc, utcnow

logger = logging.getLogger(__name__)


async def _branch(db: AsyncSession, lead: TeleCallLead) -> tuple[str, set[int]]:
    """(branch name, ids of its team leader and telecallers)."""
    from .intake import _real_team_leader, team_telecallers
    store = await db.get(Store, lead.store_id) if lead.store_id else None
    tl = await _real_team_leader(db, store)
    if tl:
        return store.name, {tl.id} | {u.id for u in await team_telecallers(db, tl)}
    members = await sheet_members(db, [lead.sheet_tl_name], roles={"Telecaller", "Team Leader"}) \
        if lead.sheet_tl_name else []
    return (store.name if store else lead.sheet_tl_name or "no branch"), {m["id"] for m in members}


async def _all_telecallers(db: AsyncSession) -> set[int]:
    return set((await db.execute(
        select(User.id).join(Role, Role.id == User.role_id)
        .where(Role.name == "Telecaller", User.is_active == True)  # noqa: E712
    )).scalars().all())


def _source(lead: TeleCallLead) -> str:
    return {"instagram": "Instagram", "facebook": "Facebook", "website": "Website",
            "meta_sheet": "Meta"}.get(lead.source_channel or "", "")


async def notify_new_lead(db: AsyncSession, lead: TeleCallLead) -> list[CrmNotification]:
    """Write the notifications for a brand-new lead (lead must be flushed)."""
    now = utcnow()
    hot = lead.priority == "hot"
    branch, team = await _branch(db, lead)
    src = _source(lead)
    what = f"{'🔥 HOT ' if hot else ''}{src + ' ' if src else ''}lead"
    detail = " · ".join(x for x in (lead.full_name, branch, lead.phone_model or lead.phone_brand) if x)
    rows: list[CrmNotification] = []

    def add(uid: int, kind: str, title: str, body: str) -> None:
        rows.append(CrmNotification(user_id=uid, lead_id=lead.id, kind=kind, title=title[:200],
                                    body=body[:300], is_hot=hot, created_at=now))

    if lead.owner_user_id:
        owner_name = (await user_names(db, [lead.owner_user_id])).get(lead.owner_user_id, "")
        add(lead.owner_user_id, "lead_assigned", f"New {what} assigned to you", detail)
        for uid in team - {lead.owner_user_id}:
            add(uid, "lead_branch", f"New {what} for {branch}", f"{detail} · given to {owner_name}")
    else:
        for uid in await _all_telecallers(db) | set(await admin_ids(db)) | team:
            add(uid, "lead_unassigned", f"Unassigned {what} — {branch}", f"{detail} · needs an owner")
    db.add_all(rows)
    return rows


def notification_dict(n: CrmNotification) -> dict:
    return {"id": n.id, "lead_id": n.lead_id, "kind": n.kind, "title": n.title, "body": n.body,
            "is_hot": bool(n.is_hot), "read": n.read_at is not None, "created_at": iso_utc(n.created_at)}


async def emit_notifications(rows: list[CrmNotification]) -> None:
    """Push to each recipient's socket room (after commit, so ids exist)."""
    if not rows:
        return
    try:
        from ...socket import sio
        for n in rows:
            await sio.emit("crm:notify", notification_dict(n), room=f"user:{n.user_id}")
    except Exception as e:  # a failed push never breaks lead intake
        logger.warning("Failed to emit lead notifications: %s", e)
