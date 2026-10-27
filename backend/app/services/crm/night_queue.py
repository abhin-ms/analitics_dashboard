"""Night queue: leads that arrive outside working hours (8 PM – 10:30 AM by
default) are not handed to a telecaller who can't call them. Each waits for
the telecaller it was routed to (queued_owner_id); from the next opening
the automation tick hands them over one at a time per telecaller, one every
queue_gap_minutes (15), hot leads first, and only then does the usual
first-call clock (5 / 15 / 60 minutes) start. A lead that arrives during
working hours goes straight to its telecaller, queue or not."""
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
    """Hold the lead for `owner` until the next opening (no owner, no first
    call, no new-lead popups yet — those come when it is handed over)."""
    lead.queued_at, lead.queued_owner_id, lead.queue_released_at = now, owner.id, None
    opens = to_ist(next_opening(now, automation["working_hours"])).strftime("%a %d %b %H:%M")
    add_activity(db, lead, "system", at=now, meta={"queued_for": owner.id},
                 notes=f"Arrived outside working hours — waiting for {owner.name}, handed over from {opens}")


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
    """The queued owner if they can still take leads, else someone on
    their team leader's team, else that team leader."""
    from .intake import pick_telecaller
    user = await db.get(User, user_id)
    if user and user.is_active and user.available_for_leads is not False:
        return user
    tl = await db.get(User, user.team_leader_id) if user and user.team_leader_id else None
    if tl and tl.is_active:
        return await pick_telecaller(db, tl) or tl
    return None


async def release_queue(db: AsyncSession, now: datetime, automation: dict) -> tuple[list, int]:
    """Hand over the next waiting lead of every telecaller whose last one
    was handed over at least queue_gap_minutes ago. Returns (new-lead
    notifications to emit, how many were handed over)."""
    if not is_working_time(now, automation["working_hours"]):
        return [], 0
    rows = (await db.execute(select(TeleCallLead).where(waiting()))).scalars().all()
    if not rows:
        return [], 0
    from .notify import notify_new_lead
    gap = timedelta(minutes=automation.get("queue_gap_minutes", 15))
    owners = sorted({r.queued_owner_id for r in rows if r.queued_owner_id})
    last = dict((await db.execute(
        select(TeleCallLead.queued_owner_id, func.max(TeleCallLead.queue_released_at))
        .where(TeleCallLead.queued_owner_id.in_(owners or [-1]), TeleCallLead.queue_released_at.isnot(None))
        .group_by(TeleCallLead.queued_owner_id))).all())
    by_owner: dict[int | None, list[TeleCallLead]] = {}
    for r in rows:
        if r.owner_user_id is not None:  # someone assigned it by hand meanwhile
            r.queue_released_at = now
            continue
        by_owner.setdefault(r.queued_owner_id, []).append(r)

    notes, released = [], 0
    for owner_id, leads in by_owner.items():
        if owner_id is None:  # the telecaller's account was deleted: an ordinary unassigned lead now
            for l in leads:
                l.queue_released_at = now
            continue
        if last.get(owner_id) and now - last[owner_id] < gap:
            continue
        lead = min(leads, key=lambda l: (l.priority != "hot", l.submitted_at or l.queued_at, l.id))
        lead.queue_released_at = now
        receiver = await _receiver(db, owner_id)
        if receiver is None:
            continue  # stays unassigned (shows in Leads → Unassigned)
        await transfer_ownership(db, lead, receiver.id, source="auto", actor_id=None, now=now,
                                 automation=automation, reason="Night lead — handed over in the morning")
        if not lead.status:
            create_followup(db, lead, kind="first_call", owner_id=receiver.id, at=now,
                            reason="Call the lead that came in overnight",
                            due_at=add_working_minutes(now, automation["first_call_minutes"],
                                                       automation["working_hours"]))
        await db.flush()
        notes += await notify_new_lead(db, lead, admins=False)  # admins were told when it arrived
        released += 1
    return notes, released
