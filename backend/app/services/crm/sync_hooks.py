"""CRM steps run by the tele-call sheet sync for every row it upserts.

The sync stays read-only towards Google Sheets. These hooks only fill the
app-owned CRM columns: parsed submission time, stage/priority, owner (sheet
"Person Calling" wins; otherwise the lead's store's team leader, passed on to
the telecaller on that team with the fewest leads today, or kept by the team
leader when the team has none), the first-call task, and follow-up
bookkeeping when an agent updates the sheet.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import Store, TeleCallLead, User
from .config import ensure_go_live, get_aliases, get_automation
from .engine import (
    RoundRobin, apply_sheet_status_change, create_alert, create_followup,
    match_user_by_name, refresh_derived, team_leader_ids, transfer_ownership,
)
from .scope import sheet_members
from .status import CLOSED_STATUSES
from .timeutil import add_working_minutes, ist_day_bounds_utc, ist_today, parse_sheet_datetime, utcnow

RECENT_WINDOW = timedelta(hours=24)
# assignment_source of a lead given out by the store → team leader → telecaller rule
STORE_ROUTED = "store_tl"


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
        self.new_notifications: list = []  # live "new lead" pushes, sent after commit
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

    # ── store → team leader → telecaller ──
    async def team_leader_for(self, lead: TeleCallLead) -> User | None:
        """The team leader of the lead's store (its own store, else the store
        its sheet tab is for); for a tab covering an area (Bangalore), or a
        store without a real team leader, the team leader on that tab."""
        from ..store_portfolio import shop_of, shop_of_sheet
        from .intake import _real_team_leader
        if not hasattr(self, "_tl_by_store"):
            self._tl_by_store: dict[int, User | None] = {}
            self._stores_by_shop: dict[str, list[Store]] = {}
            for st in (await self.db.execute(select(Store).where(Store.is_active == True))).scalars().all():  # noqa: E712
                if shop_of(st.name):
                    self._stores_by_shop.setdefault(shop_of(st.name), []).append(st)
            self._tab_tl: dict[str, User | None] = {}

        async def tl_of(store: Store) -> User | None:
            if store.id not in self._tl_by_store:
                self._tl_by_store[store.id] = await _real_team_leader(self.db, store)
            return self._tl_by_store[store.id]

        candidates: list[Store] = []
        if lead.store_id:
            st = await self.db.get(Store, lead.store_id)
            if st:
                candidates.append(st)
        candidates += self._stores_by_shop.get(shop_of_sheet(lead.sheet_tl_name) or "", [])
        for st in candidates:
            tl = await tl_of(st)
            if tl:
                return tl
        tab = lead.sheet_tl_name
        if tab not in self._tab_tl:
            leaders = [m for m in await self.members(tab) if m["role"] == "Team Leader"]
            self._tab_tl[tab] = await self.db.get(User, leaders[0]["id"]) if leaders else None
        return self._tab_tl[tab]

    async def telecaller_for(self, tl: User) -> User | None:
        """Available telecaller on this team leader's team with the fewest
        leads given out today (counting the ones handed out in this run)."""
        from .intake import team_telecallers
        if not hasattr(self, "_teams"):
            self._teams: dict[int, list[User]] = {}
            start, end = ist_day_bounds_utc(ist_today(self.now))
            self._today = dict((await self.db.execute(
                select(TeleCallLead.owner_user_id, func.count(TeleCallLead.id))
                .where(TeleCallLead.owner_user_id.isnot(None),
                       TeleCallLead.assigned_at >= start, TeleCallLead.assigned_at < end)
                .group_by(TeleCallLead.owner_user_id))).all())
        if tl.id not in self._teams:
            self._teams[tl.id] = [u for u in await team_telecallers(self.db, tl) if u.available_for_leads is not False]
        team = self._teams[tl.id]
        if not team:
            return None
        chosen = min(team, key=lambda u: (self._today.get(u.id, 0), u.id))
        self._today[chosen.id] = self._today.get(chosen.id, 0) + 1
        return chosen


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
            and (lead.owner_user_id is None or sheet_person_changed or lead.assignment_source == STORE_ROUTED)):
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

    # 2. Still no owner (nobody in "Person Calling", or a name with no app
    #    login): the store's team leader, passed on to a telecaller on their
    #    team when there is one. A team leader holding such a lead hands it on
    #    once their team gets a telecaller, while it's still open.
    if ctx.automation.get("auto_assign", True) and lead.assignment_source != "manual":
        reroute = (lead.assignment_source == STORE_ROUTED and lead.owner_user_id is not None
                   and (lead.status or "") not in CLOSED_STATUSES)
        tl = await ctx.team_leader_for(lead) if lead.owner_user_id is None or reroute else None
        # a re-route only takes leads the team leader still holds, never one a telecaller has
        if tl and (lead.owner_user_id is None or lead.owner_user_id == tl.id):
            agent = await ctx.telecaller_for(tl)
            owner = agent or (tl if lead.owner_user_id is None else None)
            if owner and owner.id != lead.owner_user_id:
                quiet = historic and lead.owner_user_id is None
                await transfer_ownership(
                    db, lead, owner.id, source=STORE_ROUTED, actor_id=None, now=ctx.now, automation=ctx.automation,
                    reason=(f"Telecaller on {tl.name}'s team" if agent else f"Team leader of the store ({tl.name}) — no telecaller on the team"),
                    record=not quiet, assigned_at=(lead.submitted_at or lead.created_at) if quiet else None,
                )
                ctx.stats["auto_assigned"] += 1

    # New-lead notifications (owner and branch, or everyone if unassigned).
    # A sheet row that attached to a lead the Meta webhook already created
    # is not new (is_new is False), so nobody is told twice.
    if tracked_new:
        from .notify import notify_new_lead
        ctx.new_notifications += await notify_new_lead(db, lead)

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
