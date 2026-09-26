"""Core telecalling-CRM operations shared by the sheet sync, the automation
tick and the API: timeline entries, follow-ups, ownership, alerts and the
"record an outcome → schedule the next step" rules."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import (
    AuditLog, CrmAlert, PriceBookEntry, Role, TeleAppointment, TeleCallLead,
    TeleLeadActivity, TeleLeadFollowup, TeleSheetAssignment, User,
)
from .status import (
    OUTCOMES, derive_priority, derive_stage, normalize_status,
)
from .timeutil import (
    add_working_minutes, ist_day_bounds_utc, ist_today, next_working_day_opening,
    to_ist, utcnow,
)

logger = logging.getLogger(__name__)


# ── small helpers ──────────────────────────────────────────────────
def norm_name(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def norm_phone(text: str | None) -> str:
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def mark_edited(lead: TeleCallLead, *fields: str) -> None:
    current = list(lead.edited_fields or [])
    changed = False
    for f in fields:
        if f not in current:
            current.append(f)
            changed = True
    if changed:
        lead.edited_fields = current  # reassign so SQLAlchemy sees the JSON change


def refresh_derived(lead: TeleCallLead) -> None:
    """Recompute stage and priority from status (respecting manual choices)."""
    lead.stage = derive_stage(lead.status, lead.stage, bool(lead.stage_manual))
    lead.priority = derive_priority(lead.stage, lead.priority, bool(lead.priority_manual))


def parse_amount(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).replace(",", "").replace("₹", "").replace("$", "").replace("Rs", "").strip()
    try:
        return float(text or 0)
    except ValueError:
        return 0.0


def match_user_by_name(name: str | None, members: list[dict], aliases: dict[str, int]) -> dict | None:
    """Match sheet "Person Calling" text to one of the sheet's users.
    Order: alias → exact full name → unique first name."""
    key = norm_name(name)
    if not key:
        return None
    by_id = {m["id"]: m for m in members}
    if key in aliases and aliases[key] in by_id:
        return by_id[aliases[key]]
    exact = [m for m in members if norm_name(m["name"]) == key]
    if len(exact) == 1:
        return exact[0]
    first = key.split(" ")[0]
    firsts = [m for m in members if norm_name(m["name"]).split(" ")[0] == first]
    if len(firsts) == 1 and (key == first or norm_name(firsts[0]["name"]).startswith(key)):
        return firsts[0]
    return None


async def user_names(db: AsyncSession, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


def add_activity(db: AsyncSession, lead: TeleCallLead, type_: str, *, user_id: int | None = None,
                 outcome: str | None = None, old_value=None, new_value=None,
                 notes: str | None = None, meta: dict | None = None,
                 at: datetime | None = None) -> TeleLeadActivity:
    act = TeleLeadActivity(
        lead_id=lead.id, user_id=user_id, type=type_, outcome=outcome,
        old_value=(str(old_value)[:200] if old_value is not None else None),
        new_value=(str(new_value)[:200] if new_value is not None else None),
        notes=notes, meta=meta, created_at=at or utcnow(),
    )
    db.add(act)
    return act


def record_audit(db: AsyncSession, user_id: int | None, action: str, resource: str,
                 resource_id: int | None, before: dict | None = None, after: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action[:50], resource=resource[:50],
                    resource_id=resource_id, before_json=before, after_json=after))


# ── follow-ups ─────────────────────────────────────────────────────
async def open_followups(db: AsyncSession, lead_id: int) -> list[TeleLeadFollowup]:
    return list((await db.execute(
        select(TeleLeadFollowup).where(
            TeleLeadFollowup.lead_id == lead_id, TeleLeadFollowup.status == "open",
        ).order_by(TeleLeadFollowup.due_at)
    )).scalars().all())


def create_followup(db: AsyncSession, lead: TeleCallLead, *, kind: str, due_at: datetime,
                    owner_id: int | None, created_by: int | None = None, reason: str | None = None,
                    attempt_no: int = 1, at: datetime | None = None) -> TeleLeadFollowup:
    fu = TeleLeadFollowup(
        lead_id=lead.id, owner_user_id=owner_id, kind=kind, due_at=due_at,
        status="open", attempt_no=attempt_no, reason=reason, created_by=created_by,
        created_at=at or utcnow(),
    )
    db.add(fu)
    if lead.next_follow_up_at is None or due_at < lead.next_follow_up_at:
        lead.next_follow_up_at = due_at
    return fu


async def close_open_followups(db: AsyncSession, lead: TeleCallLead, *, status: str,
                               user_id: int | None, outcome: str | None, now: datetime) -> list[int]:
    fus = await open_followups(db, lead.id)
    for fu in fus:
        fu.status = status
        fu.completed_at = now
        fu.completed_by = user_id
        fu.outcome = outcome
    lead.next_follow_up_at = None
    ids = [f.id for f in fus]
    await resolve_alerts_for_followups(db, ids, now)
    return ids


async def recompute_next_follow_up(db: AsyncSession, lead: TeleCallLead) -> None:
    await db.flush()
    lead.next_follow_up_at = (await db.execute(
        select(func.min(TeleLeadFollowup.due_at)).where(
            TeleLeadFollowup.lead_id == lead.id, TeleLeadFollowup.status == "open",
        )
    )).scalar()


# ── alerts ─────────────────────────────────────────────────────────
async def create_alert(db: AsyncSession, *, recipient_id: int, kind: str, title: str,
                       dedupe_key: str, level: int = 1, body: str | None = None,
                       lead: TeleCallLead | None = None, followup_id: int | None = None,
                       out: list | None = None) -> CrmAlert | None:
    exists = (await db.execute(select(CrmAlert.id).where(CrmAlert.dedupe_key == dedupe_key))).scalar()
    if exists:
        return None
    alert = CrmAlert(
        recipient_user_id=recipient_id, kind=kind, level=level, title=title[:200], body=body,
        lead_id=lead.id if lead else None, followup_id=followup_id,
        dedupe_key=dedupe_key[:150], created_at=utcnow(),
    )
    db.add(alert)
    await db.flush()
    if out is not None:
        out.append(alert)
    return alert


async def resolve_alerts_for_followups(db: AsyncSession, followup_ids: list[int], now: datetime) -> None:
    if not followup_ids:
        return
    await db.execute(
        update(CrmAlert)
        .where(CrmAlert.followup_id.in_(followup_ids), CrmAlert.resolved_at.is_(None))
        .values(resolved_at=now)
    )


async def resolve_alerts_for_lead(db: AsyncSession, lead_id: int, kinds: list[str], now: datetime) -> None:
    await db.execute(
        update(CrmAlert)
        .where(CrmAlert.lead_id == lead_id, CrmAlert.kind.in_(kinds), CrmAlert.resolved_at.is_(None))
        .values(resolved_at=now)
    )


async def team_leader_ids(db: AsyncSession, sheet: str | None, owner_id: int | None = None) -> list[int]:
    ids: set[int] = set()
    if sheet:
        rows = (await db.execute(
            select(User.id).join(TeleSheetAssignment, TeleSheetAssignment.user_id == User.id)
            .join(Role, Role.id == User.role_id)
            .where(TeleSheetAssignment.sheet_tl_name == sheet, Role.name == "Team Leader",
                   User.is_active == True)  # noqa: E712
        )).scalars().all()
        ids.update(rows)
    if owner_id:
        tl = (await db.execute(select(User.team_leader_id).where(User.id == owner_id))).scalar()
        if tl:
            ids.add(tl)
    return sorted(ids)


async def admin_ids(db: AsyncSession) -> list[int]:
    return list((await db.execute(
        select(User.id).join(Role, Role.id == User.role_id)
        .where(Role.name.in_(["Admin", "SuperAdmin"]), User.is_active == True)  # noqa: E712
    )).scalars().all())


def alert_to_dict(a: CrmAlert) -> dict:
    from .timeutil import iso_utc
    return {
        "id": a.id, "kind": a.kind, "level": a.level, "title": a.title, "body": a.body,
        "lead_id": a.lead_id, "followup_id": a.followup_id,
        "created_at": iso_utc(a.created_at), "acknowledged_at": iso_utc(a.acknowledged_at),
        "resolved_at": iso_utc(a.resolved_at),
    }


async def emit_alerts(alerts: list[CrmAlert]) -> None:
    """Push new alerts to each recipient's socket room (after commit)."""
    if not alerts:
        return
    try:
        from ...socket import sio
        for a in alerts:
            await sio.emit("crm:alert", alert_to_dict(a), room=f"user:{a.recipient_user_id}")
    except Exception as e:  # never break the caller over a notification
        logger.warning("Failed to emit crm alerts: %s", e)


# ── ownership ──────────────────────────────────────────────────────
class RoundRobin:
    """Fair assignment among available telecallers of a city sheet: fewest
    leads assigned today first, then whoever waited longest, then id."""

    def __init__(self, db: AsyncSession, now: datetime | None = None):
        self.db = db
        self.now = now or utcnow()
        self._members: dict[str, list[dict]] = {}
        self._counts: dict[int, int] = {}
        self._last: dict[int, datetime] = {}
        self._loaded_counts = False

    async def _load(self, sheet: str) -> list[dict]:
        from .scope import sheet_members
        if sheet not in self._members:
            self._members[sheet] = await sheet_members(self.db, [sheet], roles={"Telecaller"})
        if not self._loaded_counts:
            start, end = ist_day_bounds_utc(ist_today(self.now))
            rows = (await self.db.execute(
                select(TeleCallLead.owner_user_id, func.count(TeleCallLead.id), func.max(TeleCallLead.assigned_at))
                .where(TeleCallLead.owner_user_id.isnot(None),
                       TeleCallLead.assigned_at >= start, TeleCallLead.assigned_at < end)
                .group_by(TeleCallLead.owner_user_id)
            )).all()
            self._counts = {r[0]: int(r[1]) for r in rows}
            self._last = {r[0]: r[2] for r in rows if r[2]}
            self._loaded_counts = True
        return self._members[sheet]

    async def pick(self, sheet: str, exclude: set[int] | None = None) -> dict | None:
        members = [m for m in await self._load(sheet)
                   if m["available"] and m["id"] not in (exclude or set())]
        if not members:
            return None
        members.sort(key=lambda m: (self._counts.get(m["id"], 0),
                                    self._last.get(m["id"], datetime.min), m["id"]))
        chosen = members[0]
        self._counts[chosen["id"]] = self._counts.get(chosen["id"], 0) + 1
        self._last[chosen["id"]] = self.now
        return chosen


async def transfer_ownership(db: AsyncSession, lead: TeleCallLead, new_owner_id: int | None, *,
                             source: str, actor_id: int | None, now: datetime,
                             automation: dict, reason: str | None = None, record: bool = True,
                             assigned_at: datetime | None = None) -> bool:
    """Change the lead's owner. Open follow-ups are closed as 'reassigned'
    (the missed deadline stays with the old owner) and re-opened for the new
    owner; a pending first call gets a fresh first-call window.

    record=False skips the timeline entry (used only for the one-off
    back-fill of historic leads from the sheet's "Person Calling")."""
    old = lead.owner_user_id
    if old == new_owner_id:
        return False
    lead.owner_user_id = new_owner_id
    lead.assigned_at = (assigned_at or now) if new_owner_id else None
    lead.assignment_source = source if new_owner_id else None
    if old is not None:
        lead.reassign_count = (lead.reassign_count or 0) + 1
    if record:
        names = await user_names(db, [old, new_owner_id])
        add_activity(db, lead, "assignment", user_id=actor_id,
                     old_value=names.get(old) if old else "Unassigned",
                     new_value=names.get(new_owner_id) if new_owner_id else "Unassigned",
                     notes=reason, meta={"source": source, "from": old, "to": new_owner_id}, at=now)

    fus = await open_followups(db, lead.id)
    closed_ids = []
    for fu in fus:
        fu.status = "reassigned"
        fu.completed_at = now
        closed_ids.append(fu.id)
        if new_owner_id:
            if fu.kind == "first_call":
                due = add_working_minutes(now, automation["first_call_minutes"], automation["working_hours"])
            else:
                due = max(fu.due_at, now)
            db.add(TeleLeadFollowup(
                lead_id=lead.id, owner_user_id=new_owner_id, kind=fu.kind, due_at=due, status="open",
                attempt_no=(fu.attempt_no or 1) + 1, reason=fu.reason, created_by=actor_id, created_at=now,
            ))
    await resolve_alerts_for_followups(db, closed_ids, now)
    await recompute_next_follow_up(db, lead)
    return True


# ── pricing ────────────────────────────────────────────────────────
async def lookup_price(db: AsyncSession, phone_model: str | None, service_type: str | None,
                       coverage: str | None) -> Decimal | None:
    if not phone_model or not service_type:
        return None
    row = (await db.execute(
        select(PriceBookEntry.price).where(
            func.lower(PriceBookEntry.phone_model) == phone_model.strip().lower(),
            func.lower(PriceBookEntry.service_type) == service_type.strip().lower(),
            func.lower(PriceBookEntry.coverage) == (coverage or "Standard").strip().lower(),
            PriceBookEntry.is_active == True,  # noqa: E712
        )
    )).scalar()
    return row


async def refresh_potential_value(db: AsyncSession, lead: TeleCallLead) -> None:
    """Price book value for the lead's device. A converted lead keeps its
    value fixed (its sale amount is the real number)."""
    if lead.stage == "converted" and lead.potential_value is not None:
        return
    lead.potential_value = await lookup_price(db, lead.phone_model, lead.service_type, lead.coverage)


# ── outcome rules ──────────────────────────────────────────────────
async def calls_today(db: AsyncSession, lead_id: int, now: datetime) -> int:
    start, end = ist_day_bounds_utc(ist_today(now))
    return int((await db.execute(
        select(func.count(TeleLeadActivity.id)).where(
            TeleLeadActivity.lead_id == lead_id, TeleLeadActivity.type == "call",
            TeleLeadActivity.created_at >= start, TeleLeadActivity.created_at < end,
        )
    )).scalar() or 0)


def next_step_for_outcome(outcome: str, now: datetime, automation: dict, *, calls_so_far_today: int = 0,
                          callback_at: datetime | None = None,
                          appointment_at: datetime | None = None) -> tuple[datetime | None, str, str]:
    """(due_at, kind, reason) of the follow-up an outcome schedules, or
    (None, "", "") when the outcome ends the sequence. Pure function."""
    wh = automation["working_hours"]
    spec = OUTCOMES.get(outcome, {})
    if spec.get("closes") or spec.get("is_note"):
        return None, "", ""
    if outcome == "no_answer":
        return (add_working_minutes(now, automation["no_answer_retry_minutes"], wh), "call",
                "Retry after no answer")
    if outcome == "switched_off":
        return next_working_day_opening(now, wh), "call", "Retry next working day (switched off)"
    if outcome == "busy":
        if calls_so_far_today >= automation["max_calls_per_day"]:
            return (next_working_day_opening(now, wh), "call",
                    f"Busy — {automation['max_calls_per_day']} calls today, retry next working day")
        return add_working_minutes(now, automation["busy_retry_minutes"], wh), "call", "Retry after busy"
    if outcome == "callback_requested":
        return (callback_at or next_working_day_opening(now, wh)), "callback", "Customer asked for a callback"
    if outcome == "appointment_booked":
        if appointment_at:
            confirm = appointment_at - timedelta(hours=2)
            return max(confirm, now), "appointment_confirm", "Confirm the appointment"
        return next_working_day_opening(now, wh), "appointment_confirm", "Confirm the appointment"
    if outcome == "will_visit":
        return next_working_day_opening(now, wh), "call", "Confirm the visit"
    if outcome == "advance_paid":
        return next_working_day_opening(now, wh), "call", "Follow up on the advance"
    return next_working_day_opening(now, wh), "call", "Next follow-up"


async def log_outcome(db: AsyncSession, lead: TeleCallLead, actor: User, outcome: str, *,
                      automation: dict, notes: str | None = None,
                      callback_at: datetime | None = None, next_follow_up_at: datetime | None = None,
                      appointment_at: datetime | None = None, appointment_purpose: str | None = None,
                      store_id: int | None = None, sale_amount=None, actor_role: str = "",
                      now: datetime | None = None) -> dict:
    """Record what happened on a lead and schedule the next step."""
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown outcome: {outcome}")
    spec = OUTCOMES[outcome]
    now = now or utcnow()
    is_note = bool(spec.get("is_note"))
    old_status = lead.status or ""
    old_stage = lead.stage

    # An agent working an unowned lead takes it.
    if lead.owner_user_id is None and actor_role in ("Telecaller", "Salesperson") and not is_note:
        await transfer_ownership(db, lead, actor.id, source="manual", actor_id=actor.id, now=now,
                                 automation=automation, reason="Claimed by working the lead")

    new_status = spec.get("status")
    if new_status is not None and new_status != old_status:
        lead.status = new_status
        mark_edited(lead, "status")
    if spec.get("stage"):
        lead.stage = spec["stage"]
    refresh_derived(lead)
    if sale_amount not in (None, ""):
        lead.sale_amount = str(sale_amount)
        mark_edited(lead, "sale_amount")

    if not is_note:
        lead.last_contact_at = now
        if lead.first_contact_at is None:
            lead.first_contact_at = now
        lead.call_date = ist_today(now).isoformat()
        mark_edited(lead, "call_date")
        lead.is_urgent = False
    lead.edited_by_user = True

    today_calls = await calls_today(db, lead.id, now) if not is_note else 0
    add_activity(
        db, lead, "note" if is_note else "call", user_id=actor.id, outcome=outcome,
        old_value=(old_status or "No Status") if new_status and new_status != old_status else None,
        new_value=new_status if new_status and new_status != old_status else None,
        notes=notes, meta={"stage_from": old_stage, "stage_to": lead.stage}, at=now,
    )

    closed: list[int] = []
    if not is_note:
        closed = await close_open_followups(db, lead, status="done", user_id=actor.id, outcome=outcome, now=now)
        await resolve_alerts_for_lead(db, lead.id, ["first_call_overdue", "first_call_escalated",
                                                    "followup_overdue", "unassigned"], now)

    appointment = None
    if outcome == "appointment_booked" and appointment_at:
        appointment = TeleAppointment(
            lead_id=lead.id, store_id=store_id, scheduled_at=appointment_at,
            purpose=appointment_purpose or lead.service_type or "Store visit",
            attendance="scheduled", source="app", created_by=actor.id, created_at=now,
        )
        db.add(appointment)
        lead.appointment_date = to_ist(appointment_at).date().isoformat()
        mark_edited(lead, "appointment_date")

    followup = None
    due, kind, reason = next_step_for_outcome(
        outcome, now, automation, calls_so_far_today=today_calls + (0 if is_note else 1),
        callback_at=callback_at, appointment_at=appointment_at,
    )
    if next_follow_up_at and not spec.get("closes"):
        due = next_follow_up_at
        kind = kind or "call"
        reason = reason or "Follow-up"
    if due:
        followup = create_followup(db, lead, kind=kind, due_at=due, owner_id=lead.owner_user_id or actor.id,
                                   created_by=actor.id, reason=reason, at=now)
    await recompute_next_follow_up(db, lead)
    return {"closed_followups": closed, "followup": followup, "appointment": appointment}


async def set_status_from_app(db: AsyncSession, lead: TeleCallLead, new_status: str, *,
                              actor_id: int | None, automation: dict, go_live: datetime | None,
                              now: datetime | None = None) -> None:
    """Status changed through the existing Leads Update page (PUT
    /tele-call-leads/{id}). Keeps the new timeline/metrics in step without
    changing what that page does."""
    now = now or utcnow()
    old = lead.status or ""
    new = normalize_status(new_status)
    lead.status = new
    mark_edited(lead, "status")
    refresh_derived(lead)
    if new == old:
        return
    add_activity(db, lead, "status_change", user_id=actor_id, old_value=old or "No Status",
                 new_value=new or "No Status", meta={"source": "leads_update_page"}, at=now)
    if new:
        lead.last_contact_at = now
        if lead.first_contact_at is None:
            lead.first_contact_at = now
        lead.is_urgent = False
        await _advance_tracked_lead(db, lead, new, actor_id=actor_id, automation=automation,
                                    go_live=go_live, now=now, source="app")


async def apply_sheet_status_change(db: AsyncSession, lead: TeleCallLead, old: str, new: str, *,
                                    automation: dict, go_live: datetime | None, now: datetime) -> None:
    """The status changed in the SHEET (agent kept working in the sheet)."""
    add_activity(db, lead, "status_change", user_id=None, old_value=old or "No Status",
                 new_value=new or "No Status", meta={"source": "sheet"}, at=now)
    if new:
        lead.last_contact_at = now
        if lead.first_contact_at is None:
            lead.first_contact_at = now
        lead.is_urgent = False
        await _advance_tracked_lead(db, lead, new, actor_id=lead.owner_user_id, automation=automation,
                                    go_live=go_live, now=now, source="sheet")


async def _advance_tracked_lead(db: AsyncSession, lead: TeleCallLead, new_status: str, *,
                                actor_id: int | None, automation: dict, go_live: datetime | None,
                                now: datetime, source: str) -> None:
    """For leads tracked by the CRM (received after go-live): a status set
    outside the Log-activity dialog still completes the pending follow-up and
    schedules the next one with the same rules."""
    if go_live is None or lead.created_at is None or lead.created_at < go_live:
        return
    from .status import STATUS_TO_OUTCOME
    outcome = STATUS_TO_OUTCOME.get(new_status)
    if not outcome:
        return
    await close_open_followups(db, lead, status="done", user_id=actor_id, outcome=f"{source}:{outcome}", now=now)
    await resolve_alerts_for_lead(db, lead.id, ["first_call_overdue", "first_call_escalated",
                                                "followup_overdue", "unassigned"], now)
    due, kind, reason = next_step_for_outcome(outcome, now, automation)
    if due and lead.owner_user_id:
        create_followup(db, lead, kind=kind, due_at=due, owner_id=lead.owner_user_id,
                        created_by=None, reason=reason, at=now)
    await recompute_next_follow_up(db, lead)
