"""CRM steps run by the tele-call sheet sync for every row it upserts.

The sync stays read-only towards Google Sheets. These hooks only fill the
app-owned CRM columns: parsed submission time, stage/priority, owner (sheet
"Person Calling" wins, otherwise round-robin for brand-new leads), the
first-call task, and follow-up bookkeeping when an agent updates the sheet.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import TeleCallLead
from .config import ensure_go_live, get_aliases, get_automation
from .engine import (
    RoundRobin, apply_sheet_status_change, create_alert, create_followup,
    match_user_by_name, refresh_derived, team_leader_ids, transfer_ownership,
)
from .scope import sheet_members
from .timeutil import add_working_minutes, parse_sheet_datetime, utcnow

RECENT_WINDOW = timedelta(hours=24)


class SyncContext:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.now = utcnow()
        self.automation: dict = {}
        self.aliases: dict[str, int] = {}
        self.go_live: datetime | None = None
        self.tracking_active = False
        self.round_robin = RoundRobin(db, self.now)
        self.new_alerts: list = []
        self._members: dict[str, list[dict]] = {}
        self.stats = {"auto_assigned": 0, "sheet_assigned": 0, "first_call_tasks": 0, "unassigned_new": 0}

    @classmethod
    async def build(cls, db: AsyncSession) -> "SyncContext":
        ctx = cls(db)
        ctx.automation = await get_automation(db)
        ctx.aliases = await get_aliases(db)
        ctx.go_live, created_now = await ensure_go_live(db)
        # On the very first run after the upgrade every row is historic, so
        # nothing gets SLA timers or automatic assignment.
        ctx.tracking_active = bool(ctx.automation.get("enabled", True)) and not created_now
        return ctx

    async def members(self, sheet: str) -> list[dict]:
        if sheet not in self._members:
            self._members[sheet] = await sheet_members(self.db, [sheet])
        return self._members[sheet]

    def is_recent(self, lead: TeleCallLead) -> bool:
        return lead.submitted_at is None or lead.submitted_at >= self.now - RECENT_WINDOW


async def after_upsert(ctx: SyncContext, lead: TeleCallLead, *, is_new: bool,
                       sheet_person_calling: str, old_status: str, status_changed: bool,
                       sheet_person_changed: bool = False) -> None:
    db = ctx.db
    if lead.submitted_at is None and lead.created_time:
        lead.submitted_at = parse_sheet_datetime(lead.created_time)
    refresh_derived(lead)

    tracked_new = is_new and ctx.tracking_active and ctx.is_recent(lead)
    # Historic = everything seen on the go-live run, anything received before
    # go-live, and old rows that only now appeared in the sheet.
    pre_go_live = lead.created_at is None or ctx.go_live is None or lead.created_at < ctx.go_live
    historic = (not ctx.tracking_active) or pre_go_live or (is_new and not ctx.is_recent(lead))

    # 1. Ownership — the sheet's "Person Calling" wins when the lead has no
    #    owner yet or that sheet cell was just changed, unless someone
    #    reassigned the lead by hand in the app. (Checking for a *change*
    #    stops the sync undoing the automatic 15-minute reassignment.)
    if (lead.assignment_source != "manual" and sheet_person_calling
            and (lead.owner_user_id is None or sheet_person_changed)):
        matched = match_user_by_name(sheet_person_calling, await ctx.members(lead.sheet_tl_name), ctx.aliases)
        if matched and lead.owner_user_id != matched["id"]:
            quiet_backfill = historic and lead.owner_user_id is None
            await transfer_ownership(
                db, lead, matched["id"], source="sheet", actor_id=None, now=ctx.now,
                automation=ctx.automation, reason="Person Calling in the sheet",
                record=not quiet_backfill,
                assigned_at=(lead.submitted_at or lead.created_at) if quiet_backfill else None,
            )
            ctx.stats["sheet_assigned"] += 1

    # 2. Brand-new lead with nobody in "Person Calling": round-robin.
    if (tracked_new and lead.owner_user_id is None and not sheet_person_calling
            and ctx.automation.get("auto_assign", True)):
        chosen = await ctx.round_robin.pick(lead.sheet_tl_name)
        if chosen:
            await transfer_ownership(db, lead, chosen["id"], source="auto", actor_id=None, now=ctx.now,
                                     automation=ctx.automation, reason="Round-robin to an available telecaller")
            ctx.stats["auto_assigned"] += 1

    # 3. First-call task (due N working minutes after the app received it).
    if tracked_new and not lead.status:
        if lead.owner_user_id:
            due = add_working_minutes(lead.created_at or ctx.now, ctx.automation["first_call_minutes"],
                                      ctx.automation["working_hours"])
            create_followup(db, lead, kind="first_call", due_at=due, owner_id=lead.owner_user_id,
                            reason="First call for a new Meta lead", at=ctx.now)
            ctx.stats["first_call_tasks"] += 1
        else:
            ctx.stats["unassigned_new"] += 1
            for tl_id in await team_leader_ids(db, lead.sheet_tl_name):
                await create_alert(
                    db, recipient_id=tl_id, kind="unassigned", level=2, lead=lead,
                    title="New lead has no owner",
                    body=f"{lead.full_name} ({lead.sheet_tl_name}) — no available telecaller. Assign an owner.",
                    dedupe_key=f"unassigned:{lead.id}:{tl_id}", out=ctx.new_alerts,
                )
        return

    # 4. Existing lead whose status was changed in the sheet.
    if status_changed and not is_new:
        await apply_sheet_status_change(db, lead, old_status, lead.status or "",
                                        automation=ctx.automation, go_live=ctx.go_live, now=ctx.now)
