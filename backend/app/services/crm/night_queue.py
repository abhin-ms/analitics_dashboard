"""Night queue: a lead that arrives outside working hours (8 PM – 10:30 AM by
default) is given to its telecaller at once — it's in their list and
counted as theirs — but nobody is disturbed: no WhatsApp, no pop-up and no
first-call task until the next opening. From then the automation tick tells
each telecaller about their night leads one at a time, one every
queue_gap_minutes (5), hot ones first, and each lead's first-call clock
(5 / 15 / 60 minutes) starts when its own message goes out. A lead that
arrives during working hours goes straight to its telecaller as usual.

queued_at / queued_owner_id / queue_released_at mark a lead whose owner
hasn't been told yet ("waiting")."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import TeleCallLead, User
from .engine import add_activity, create_followup, transfer_ownership
from .timeutil import add_working_minutes, is_working_time, next_opening, to_ist


def waiting():
    """SQL filter: still waiting in the night queue."""
    return TeleCallLead.queued_at.isnot(None) & TeleCallLead.queue_released_at.is_(None)


def not_waiting():
    return or_(TeleCallLead.queued_at.is_(None), TeleCallLead.queue_released_at.isnot(None))


def should_queue(now: datetime, automation: dict) -> bool:
    return bool(automation.get("night_queue", True)) and not is_working_time(now, automation["working_hours"])


def queue_lead(db: AsyncSession, lead: TeleCallLead, owner: User, *, now: datetime, automation: dict) -> None:
    """Give the lead to `owner` now, quietly: they are told (and the
    first-call clock starts) at the next opening. assigned_at stays empty
    until then, so the lead counts once in the day's share-out."""
    lead.queued_at, lead.queued_owner_id, lead.queue_released_at = now, owner.id, None
    lead.owner_user_id, lead.assignment_source, lead.assigned_at = owner.id, "auto", None
    opens = to_ist(next_opening(now, automation["working_hours"])).strftime("%a %d %b %H:%M")
    add_activity(db, lead, "assignment", at=now, old_value="Unassigned", new_value=owner.name,
                 meta={"source": "night", "to": owner.id, "queued_for": owner.id},
                 notes=f"Arrived outside working hours — given to {owner.name}, who is told on {opens}")


async def queued_counts(db: AsyncSession, user_ids: list[int]) -> dict[int, int]:
    """Leads waiting per telecaller, so the night's leads are shared out
    instead of all going to whoever had the fewest today."""
    if not user_ids:
        return {}
    return dict((await db.execute(
        select(TeleCallLead.queued_owner_id, func.count(TeleCallLead.id))
        .where(waiting(), TeleCallLead.queued_owner_id.in_(user_ids))
        .group_by(TeleCallLead.queued_owner_id))).all())


async def _receiver(db: AsyncSession, user_id: int) -> User | None:
    """The queued owner if they can still take leads, else another
    telecaller of the same store, else their team leader."""
    from ...models.models import Store
    from .intake import pick_telecaller
    user = await db.get(User, user_id)
    if user and user.is_active and user.available_for_leads is not False:
        return user
    tl = await db.get(User, user.team_leader_id) if user and user.team_leader_id else None
    if tl and tl.is_active:
        store = await db.get(Store, user.store_id) if user.store_id else None
        return await pick_telecaller(db, tl, store) or tl
    return None


async def release_queue(db: AsyncSession, now: datetime, automation: dict) -> tuple[list, int]:
    """From opening, tell each telecaller about their night leads one at a
    time (hot first, then oldest), one every queue_gap_minutes, and start
    that lead's first-call clock. A lead someone else took meanwhile, or one
    already worked, is just marked as told (it uses no slot). Returns
    (new-lead notifications to emit, how many were handed over)."""
    if not is_working_time(now, automation["working_hours"]):
        return [], 0
    rows = (await db.execute(select(TeleCallLead).where(waiting()))).scalars().all()
    if not rows:
        return [], 0
    from .notify import notify_new_lead
    gap = timedelta(minutes=automation.get("queue_gap_minutes", 5))
    owners = sorted({r.queued_owner_id for r in rows if r.queued_owner_id})
    # when each telecaller was last told about a night lead (a told lead's
    # assigned_at is the moment it was released)
    last = dict((await db.execute(
        select(TeleCallLead.queued_owner_id, func.max(TeleCallLead.queue_released_at))
        .where(TeleCallLead.queued_owner_id.in_(owners or [-1]), TeleCallLead.queue_released_at.isnot(None),
               TeleCallLead.assigned_at == TeleCallLead.queue_released_at)
        .group_by(TeleCallLead.queued_owner_id))).all())
    notes, released, told = [], 0, set()
    for lead in sorted(rows, key=lambda l: (l.priority != "hot", l.submitted_at or l.queued_at, l.id)):
        if lead.owner_user_id is not None and lead.owner_user_id != lead.queued_owner_id:
            lead.queue_released_at = now  # someone gave it to another person meanwhile (and they were told then)
            continue
        if lead.status:  # already called at night
            lead.queue_released_at, lead.assigned_at = now, lead.assigned_at or lead.queued_at
            continue
        owner_id = lead.queued_owner_id
        if owner_id in told or (owner_id in last and now - last[owner_id] < gap):
            continue  # this telecaller's next one comes after the gap
        told.add(owner_id)
        lead.queue_released_at = now
        receiver = await _receiver(db, owner_id) if owner_id else None
        if receiver is None:  # the telecaller is gone and has no team leader: an ordinary unassigned lead
            if lead.owner_user_id is not None:
                await transfer_ownership(db, lead, None, source="auto", actor_id=None, now=now,
                                         automation=automation, reason="Night lead — its telecaller can't take it")
            continue
        if receiver.id != lead.owner_user_id:  # Away / left since: the store's next telecaller (or the team leader)
            count = lead.reassign_count or 0
            await transfer_ownership(db, lead, receiver.id, source="auto", actor_id=None, now=now,
                                     automation=automation, reason="Night lead — its telecaller isn't available")
            lead.reassign_count = count  # not a missed-call reassignment: the 15-minute rule still applies once
        lead.assigned_at = now
        create_followup(db, lead, kind="first_call", owner_id=receiver.id, at=now,
                        reason="Call the lead that came in overnight",
                        due_at=add_working_minutes(now, automation["first_call_minutes"], automation["working_hours"]))
        await db.flush()
        notes += await notify_new_lead(db, lead, admins=False)  # admins were told when it arrived
        released += 1
    return notes, released
