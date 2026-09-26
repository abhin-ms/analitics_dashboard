"""Automation tick (every minute) and weekly performance notifications.

First contact for a new Meta lead (working minutes, CRM receipt time):
  * after first_call_minutes (5): alert the owner, mark the lead urgent
  * after reassign_minutes (15): reassign ONCE to another available
    telecaller of the city; if nobody is available, alert the team leader
  * after escalate_minutes (60): escalate to the team leader
Overdue follow-ups: owner first, then team leader, then admin.
Alerts resolve themselves when the underlying follow-up is handled.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import CrmAlert, TeleCallLead, TeleLeadFollowup
from .config import get_automation, get_targets
from .engine import (
    RoundRobin, add_activity, admin_ids, create_alert, emit_alerts,
    team_leader_ids, transfer_ownership, user_names,
)
from .timeutil import ist_today, to_ist, utcnow, working_minutes_between

logger = logging.getLogger(__name__)


async def resolve_stale_alerts(db: AsyncSession, now) -> None:
    await db.execute(
        update(CrmAlert)
        .where(CrmAlert.resolved_at.is_(None), CrmAlert.followup_id.isnot(None),
               CrmAlert.followup_id.in_(
                   select(TeleLeadFollowup.id).where(TeleLeadFollowup.status != "open")))
        .values(resolved_at=now)
    )
    await db.execute(
        update(CrmAlert)
        .where(CrmAlert.resolved_at.is_(None), CrmAlert.kind.in_(["unassigned", "no_agent_available"]),
               CrmAlert.lead_id.in_(select(TeleCallLead.id).where(TeleCallLead.owner_user_id.isnot(None))))
        .values(resolved_at=now)
    )


async def run_automation_tick(db: AsyncSession, now=None) -> dict:
    automation = await get_automation(db)
    now = now or utcnow()
    stats = {"alerts": 0, "reassigned": 0, "escalated": 0, "skipped": False}
    if not automation.get("enabled", True):
        stats["skipped"] = True
        return stats
    wh = automation["working_hours"]
    new_alerts: list = []
    rr = RoundRobin(db, now)
    tl_cache: dict[tuple, list[int]] = {}

    async def tls(sheet, owner):
        key = (sheet, owner)
        if key not in tl_cache:
            tl_cache[key] = await team_leader_ids(db, sheet, owner)
        return tl_cache[key]

    # ── A. first calls ──
    rows = (await db.execute(
        select(TeleLeadFollowup, TeleCallLead)
        .join(TeleCallLead, TeleCallLead.id == TeleLeadFollowup.lead_id)
        .where(TeleLeadFollowup.status == "open", TeleLeadFollowup.kind == "first_call")
    )).all()
    for fu, lead in rows:
        elapsed = working_minutes_between(fu.created_at or now, now, wh)
        since_receipt = working_minutes_between(lead.created_at or fu.created_at or now, now, wh)
        n = automation["first_call_minutes"]

        if elapsed >= n and fu.owner_user_id:
            lead.is_urgent = True
            if await create_alert(
                db, recipient_id=fu.owner_user_id, kind="first_call_overdue", level=1, lead=lead,
                followup_id=fu.id, title="First call overdue",
                body=f"{lead.full_name} ({lead.sheet_tl_name}) — call within {n} minutes was missed. Call now.",
                dedupe_key=f"fc:{fu.id}", out=new_alerts,
            ):
                stats["alerts"] += 1

        if (elapsed >= automation["reassign_minutes"] and (lead.reassign_count or 0) == 0
                and lead.assignment_source != "manual"):
            chosen = await rr.pick(lead.sheet_tl_name, exclude={fu.owner_user_id} if fu.owner_user_id else None)
            if chosen:
                names = await user_names(db, [fu.owner_user_id])
                await transfer_ownership(
                    db, lead, chosen["id"], source="auto", actor_id=None, now=now, automation=automation,
                    reason=f"No first call within {automation['reassign_minutes']} minutes"
                           f" by {names.get(fu.owner_user_id, 'the owner')} — reassigned once",
                )
                await create_alert(
                    db, recipient_id=chosen["id"], kind="reassigned_to_you", level=1, lead=lead,
                    title="Lead reassigned to you — call within 5 minutes",
                    body=f"{lead.full_name} ({lead.sheet_tl_name}) was not called in time and is now yours.",
                    dedupe_key=f"reassigned:{lead.id}:{chosen['id']}", out=new_alerts,
                )
                stats["reassigned"] += 1
                continue
            for tl_id in await tls(lead.sheet_tl_name, fu.owner_user_id):
                await create_alert(
                    db, recipient_id=tl_id, kind="no_agent_available", level=2, lead=lead, followup_id=fu.id,
                    title="No available agent to reassign",
                    body=f"{lead.full_name} ({lead.sheet_tl_name}) still has no first call and no other agent is available.",
                    dedupe_key=f"noagent:{fu.id}:{tl_id}", out=new_alerts,
                )

        if since_receipt >= automation["escalate_minutes"] and lead.escalated_at is None:
            lead.escalated_at = now
            add_activity(db, lead, "system", notes=f"Escalated to team leader — no first call within "
                                                   f"{automation['escalate_minutes']} minutes", at=now)
            for tl_id in await tls(lead.sheet_tl_name, fu.owner_user_id):
                await create_alert(
                    db, recipient_id=tl_id, kind="first_call_escalated", level=2, lead=lead, followup_id=fu.id,
                    title="Escalation: first call still pending",
                    body=f"{lead.full_name} ({lead.sheet_tl_name}) — no call after "
                         f"{automation['escalate_minutes']} minutes. One owner stays accountable.",
                    dedupe_key=f"esc:{lead.id}:{tl_id}", out=new_alerts,
                )
            stats["escalated"] += 1

    # ── B. overdue follow-ups: owner → team leader → admin ──
    rows = (await db.execute(
        select(TeleLeadFollowup, TeleCallLead)
        .join(TeleCallLead, TeleCallLead.id == TeleLeadFollowup.lead_id)
        .where(TeleLeadFollowup.status == "open", TeleLeadFollowup.kind != "first_call",
               TeleLeadFollowup.due_at < now)
    )).all()
    admins = None
    for fu, lead in rows:
        overdue = working_minutes_between(fu.due_at, now, wh)
        if overdue <= 0:
            continue
        when = to_ist(fu.due_at).strftime("%d %b %H:%M")
        if fu.owner_user_id:
            await create_alert(
                db, recipient_id=fu.owner_user_id, kind="followup_overdue", level=1, lead=lead,
                followup_id=fu.id, title="Follow-up overdue",
                body=f"{lead.full_name} — {fu.reason or 'follow-up'} was due {when}. "
                     f"Complete it and record the outcome.",
                dedupe_key=f"fo:{fu.id}", out=new_alerts,
            )
        if overdue >= automation["overdue_tl_minutes"]:
            for tl_id in await tls(lead.sheet_tl_name, fu.owner_user_id):
                await create_alert(
                    db, recipient_id=tl_id, kind="followup_overdue", level=2, lead=lead, followup_id=fu.id,
                    title="Team follow-up overdue",
                    body=f"{lead.full_name} — {fu.reason or 'follow-up'} still open, due {when}.",
                    dedupe_key=f"fo_tl:{fu.id}:{tl_id}", out=new_alerts,
                )
        if overdue >= automation["overdue_admin_minutes"]:
            if admins is None:
                admins = await admin_ids(db)
            for aid in admins:
                await create_alert(
                    db, recipient_id=aid, kind="followup_overdue", level=3, lead=lead, followup_id=fu.id,
                    title="Unresolved overdue follow-up",
                    body=f"{lead.full_name} ({lead.sheet_tl_name}) — still open after team leader alert.",
                    dedupe_key=f"fo_ad:{fu.id}:{aid}", out=new_alerts,
                )

    # ── C. weekly reviews left unresolved for 2 days go to admin ──
    stale_reviews = (await db.execute(
        select(CrmAlert).where(CrmAlert.kind == "weekly_review", CrmAlert.resolved_at.is_(None),
                               CrmAlert.level == 2, CrmAlert.created_at < now - timedelta(days=2))
    )).scalars().all()
    if stale_reviews:
        if admins is None:
            admins = await admin_ids(db)
        for r in stale_reviews:
            for aid in admins:
                await create_alert(
                    db, recipient_id=aid, kind="weekly_review", level=3, title=f"Unreviewed: {r.title}",
                    body=r.body, dedupe_key=f"weekly_admin:{r.id}:{aid}", out=new_alerts,
                )

    await resolve_stale_alerts(db, now)
    await db.commit()
    await emit_alerts(new_alerts)
    stats["alerts"] = len(new_alerts)
    return stats


async def generate_weekly_notifications(db: AsyncSession, today: date | None = None) -> int:
    """Monday job: for last Mon–Sun, notify team leaders about agents below
    target (never for a low-sample agent's conversion — only SLA misses)."""
    from .metrics import agent_report
    from .scope import sheet_members

    now = utcnow()
    today = today or ist_today(now)
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    automation = await get_automation(db)
    targets = await get_targets(db)
    agents = await sheet_members(db, None, roles={"Telecaller"})
    rows = await agent_report(db, agents, last_monday, last_sunday, now=now,
                              automation=automation, targets=targets)
    created: list = []
    week = last_monday.isoformat()
    for r in rows:
        problems = []
        if r["below_target"]["first_call"]:
            problems.append(f"{r['first_calls_on_time']}/{r['first_calls_total']} first calls within "
                            f"{automation['first_call_minutes']} minutes (target {targets['first_call_pct']}%)")
        if r["below_target"]["followups"]:
            problems.append(f"{r['followups_on_time']}/{r['followups_total']} follow-ups on time "
                            f"(target {targets['followup_on_time_pct']}%)")
        if not problems:
            continue
        note = " Low lead volume: do not rank conversion yet." if r["low_sample"] else ""
        for sheet in r.get("sheets") or [None]:
            for tl_id in await team_leader_ids(db, sheet, r["user_id"]):
                await create_alert(
                    db, recipient_id=tl_id, kind="weekly_review", level=2,
                    title=f"{r['name']} · Review response and follow-up habits",
                    body="; ".join(problems) + "." + note,
                    dedupe_key=f"weekly:{week}:{r['user_id']}:{tl_id}", out=created,
                )
    await db.commit()
    await emit_alerts(created)
    return len(created)
