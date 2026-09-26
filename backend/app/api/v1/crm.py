"""Telecalling CRM API — leads workspace, daily work, pipeline and alerts.

Sits on top of the sheet-synced tele_call_leads table. Access follows the
same role rules as /tele-call-leads (see services/crm/scope.py). Nothing
here writes to Google Sheets.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user
from ...db.session import get_db
from ...models.models import (
    CrmAlert, CrmSavedView, PriceBookEntry, Store, TeleAppointment, TeleCallLead,
    TeleLeadActivity, TeleLeadFollowup, User,
)
from ...services.crm import metrics as crm_metrics
from ...services.crm.config import ensure_go_live, get_automation
from ...services.crm.engine import (
    RoundRobin, add_activity, alert_to_dict, create_followup, emit_alerts, log_outcome,
    mark_edited, parse_amount, record_audit, recompute_next_follow_up, refresh_derived,
    refresh_potential_value, resolve_alerts_for_followups, transfer_ownership, user_names,
)
from ...services.crm.scope import (
    CrmScope, get_scope, lead_filter, lead_in_scope, sheet_members, visible_agents,
)
from ...services.crm.status import (
    CLOSED_STAGES, NO_STATUS, OUTCOMES, PRIORITIES, STAGE_KEYS, STAGE_LABELS, STAGES, STATUSES,
    derive_priority,
)
from ...services.crm.timeutil import (
    add_working_minutes, ist_day_bounds_utc, ist_today, iso_utc, parse_client_datetime,
    parse_sheet_datetime, to_ist, utcnow,
)
from ...services.tele_call_sync import TELE_CALL_SHEETS

router = APIRouter(prefix="/crm", tags=["Telecalling CRM"])

DEFAULT_COVERAGES = ["Standard", "AppleCare+", "Samsung Care+", "Third-party insurance"]
DEFAULT_SERVICES = ["Screen repair", "Battery replacement"]


# ── helpers ────────────────────────────────────────────────────────
async def require_scope(db: AsyncSession, user: User) -> CrmScope:
    scope = await get_scope(db, user)
    if not scope.has_access:
        raise HTTPException(status_code=403, detail="Your role has no access to telecalling leads")
    return scope


async def load_lead(db: AsyncSession, lead_id: int, scope: CrmScope) -> TeleCallLead:
    lead = (await db.execute(select(TeleCallLead).where(TeleCallLead.id == lead_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead_in_scope(lead, scope):
        raise HTTPException(status_code=403, detail="Access denied to this lead")
    return lead


def _num(v):
    return float(v) if v is not None else None


def lead_row(l: TeleCallLead, names: dict[int, str], first_call_ids: set[int] | None = None) -> dict:
    return {
        "id": l.id,
        "full_name": l.full_name,
        "phone": l.phone,
        "email": l.email,
        "city": l.sheet_tl_name,
        "lead_source": l.lead_source,
        "created_time": l.created_time,
        "submitted_at": iso_utc(l.submitted_at),
        "received_at": iso_utc(l.created_at),
        "status": l.status or "",
        "status_label": l.status or NO_STATUS,
        "sheet_status_raw": l.sheet_status_raw,
        "stage": l.stage or "new",
        "stage_label": STAGE_LABELS.get(l.stage or "new", l.stage),
        "priority": l.priority or "warm",
        "priority_manual": bool(l.priority_manual),
        "stage_manual": bool(l.stage_manual),
        "owner_user_id": l.owner_user_id,
        "owner_name": names.get(l.owner_user_id) if l.owner_user_id else None,
        "assignment_source": l.assignment_source,
        "reassign_count": l.reassign_count or 0,
        "person_calling": l.person_calling,
        "salesperson": l.salesperson,
        "next_follow_up_at": iso_utc(l.next_follow_up_at),
        "last_contact_at": iso_utc(l.last_contact_at),
        "first_contact_at": iso_utc(l.first_contact_at),
        "phone_model": l.phone_model,
        "service_type": l.service_type,
        "coverage": l.coverage,
        "potential_value": _num(l.potential_value),
        "sale_amount": l.sale_amount,
        "sale_amount_value": parse_amount(l.sale_amount) if l.sale_amount else None,
        "product": l.product,
        "remarks": l.remarks,
        "appointment_date": l.appointment_date,
        "call_date": l.call_date,
        "is_urgent": bool(l.is_urgent),
        "first_call_pending": bool(first_call_ids and l.id in first_call_ids),
        "from_sheet": bool(l.spreadsheet_id),
        "escalated": l.escalated_at is not None,
    }


async def pending_first_calls(db: AsyncSession, lead_ids: list[int]) -> set[int]:
    if not lead_ids:
        return set()
    return set((await db.execute(
        select(TeleLeadFollowup.lead_id).where(
            TeleLeadFollowup.lead_id.in_(lead_ids), TeleLeadFollowup.status == "open",
            TeleLeadFollowup.kind == "first_call",
        )
    )).scalars().all())


def tab_clause(tab: str, user_id: int, now: datetime):
    day_start, day_end = ist_day_bounds_utc(ist_today(now))
    open_stage = func.coalesce(TeleCallLead.stage, "new").notin_(list(CLOSED_STAGES))
    if tab == "mine":
        return TeleCallLead.owner_user_id == user_id
    if tab == "today":
        return and_(TeleCallLead.next_follow_up_at >= day_start, TeleCallLead.next_follow_up_at < day_end)
    if tab == "overdue":
        return TeleCallLead.next_follow_up_at < now
    if tab == "unassigned":
        return and_(TeleCallLead.owner_user_id.is_(None), open_stage)
    if tab == "new":
        return func.coalesce(TeleCallLead.status, "") == ""
    return None


def filters_clause(*, status: str, stage: str, owner: str, sheet: str, priority: str, q: str,
                   user_id: int, start: str = "", end: str = ""):
    clauses = []
    if status:
        clauses.append(func.coalesce(TeleCallLead.status, "") == ("" if status == NO_STATUS else status))
    if stage:
        clauses.append(func.coalesce(TeleCallLead.stage, "new") == stage)
    if owner:
        if owner == "me":
            clauses.append(TeleCallLead.owner_user_id == user_id)
        elif owner == "none":
            clauses.append(TeleCallLead.owner_user_id.is_(None))
        elif owner.isdigit():
            clauses.append(TeleCallLead.owner_user_id == int(owner))
    if sheet:
        clauses.append(TeleCallLead.sheet_tl_name == sheet)
    if priority:
        clauses.append(func.coalesce(TeleCallLead.priority, "warm") == priority)
    if q:
        like = f"%{q.strip()}%"
        clauses.append(or_(TeleCallLead.full_name.ilike(like), TeleCallLead.phone.ilike(like),
                           TeleCallLead.phone_model.ilike(like), TeleCallLead.product.ilike(like),
                           TeleCallLead.email.ilike(like)))
    if start or end:
        try:
            d_start = date.fromisoformat(start) if start else date(2000, 1, 1)
            d_end = date.fromisoformat(end) if end else date(2100, 1, 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD")
        s_utc, e_utc = crm_metrics.period_bounds(d_start, d_end)
        clauses.append(crm_metrics.lead_date_col() >= s_utc)
        clauses.append(crm_metrics.lead_date_col() < e_utc)
    return and_(*clauses) if clauses else None


# ── meta ───────────────────────────────────────────────────────────
@router.get("/meta")
async def crm_meta(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Everything the CRM pages need to render filters and dialogs."""
    from ...core.deps import get_user_permissions
    scope = await require_scope(db, user)
    automation = await get_automation(db)
    perms = await get_user_permissions(user, db)
    models = (await db.execute(
        select(PriceBookEntry.phone_model).where(PriceBookEntry.is_active == True).distinct()  # noqa: E712
    )).scalars().all()
    services = (await db.execute(
        select(PriceBookEntry.service_type).where(PriceBookEntry.is_active == True).distinct()  # noqa: E712
    )).scalars().all()
    coverages = (await db.execute(select(PriceBookEntry.coverage).distinct())).scalars().all()
    all_sheets = [s["tl_name"] for s in TELE_CALL_SHEETS]
    sheets = all_sheets if scope.is_admin else scope.sheets
    assignable = await sheet_members(db, sheets if not scope.is_admin else None,
                                     roles={"Telecaller", "Team Leader", "Salesperson"})
    stores = (await db.execute(select(Store.id, Store.name).where(Store.is_active == True)  # noqa: E712
                               .order_by(Store.name))).all()
    return {
        "role": scope.role,
        "user": {"id": user.id, "name": user.name, "available": user.available_for_leads is not False},
        "statuses": [NO_STATUS] + STATUSES,
        "stages": STAGES,
        "priorities": PRIORITIES,
        "outcomes": [{"key": k, **{kk: vv for kk, vv in v.items() if kk in ("label", "status", "closes", "is_note")}}
                     for k, v in OUTCOMES.items()],
        "sheets": sheets,
        "all_sheets": all_sheets,
        "people": [{"id": m["id"], "name": m["name"], "role": m["role"], "sheets": m["sheets"],
                    "available": m["available"]} for m in assignable],
        "phone_models": sorted(set(models)),
        "service_types": sorted(set(services) | set(DEFAULT_SERVICES)),
        "coverages": list(dict.fromkeys(DEFAULT_COVERAGES + sorted(coverages))),
        "stores": [{"id": s[0], "name": s[1]} for s in stores],
        "can": {
            "reassign": scope.can_reassign,
            "edit_settings": scope.can_edit_settings,
            "export": any(p["resource"] == "leads" and p["action"] == "export" for p in perms),
            "edit_prices": scope.can_edit_settings or any(
                p["resource"] == "settings" and p["action"] == "edit" for p in perms),
            "see_team": scope.is_admin or scope.is_tl,
        },
        "automation": {k: automation[k] for k in (
            "first_call_minutes", "reassign_minutes", "escalate_minutes", "working_hours", "enabled")},
        "now": iso_utc(utcnow()),
    }


# ── leads ──────────────────────────────────────────────────────────
@router.get("/leads")
async def list_leads(
    tab: str = Query("all"), status: str = Query(""), stage: str = Query(""),
    owner: str = Query(""), sheet: str = Query(""), priority: str = Query(""),
    q: str = Query(""), start: str = Query(""), end: str = Query(""),
    sort: str = Query("smart"), group_by: str = Query(""),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    scope = await require_scope(db, user)
    now = utcnow()
    base = lead_filter(scope)
    tabc = tab_clause(tab, user.id, now)
    other = filters_clause(status="", stage=stage, owner=owner, sheet=sheet, priority=priority, q=q,
                           user_id=user.id, start=start, end=end)
    statusc = filters_clause(status=status, stage="", owner="", sheet="", priority="", q="", user_id=user.id)

    def where(*extra):
        conds = [base] + [c for c in extra if c is not None]
        return and_(*conds)

    # chips: counts per status for everything except the status filter
    rows = (await db.execute(
        select(func.coalesce(TeleCallLead.status, ""), func.count(TeleCallLead.id))
        .where(where(tabc, other)).group_by(func.coalesce(TeleCallLead.status, ""))
    )).all()
    counts = {(s or NO_STATUS): int(c) for s, c in rows}
    status_counts = {s: counts[s] for s in [NO_STATUS] + STATUSES if s in counts}
    for s, c in counts.items():
        if s not in status_counts:
            status_counts[s] = c

    tab_counts = {}
    for t in ("all", "mine", "today", "overdue", "unassigned", "new"):
        tab_counts[t] = int((await db.execute(
            select(func.count(TeleCallLead.id)).where(where(tab_clause(t, user.id, now), other, statusc))
        )).scalar() or 0)

    final = where(tabc, other, statusc)
    total = tab_counts.get(tab) if tab in tab_counts and tab != "all" else None
    if total is None:
        total = int((await db.execute(select(func.count(TeleCallLead.id)).where(final))).scalar() or 0)

    lead_date = crm_metrics.lead_date_col()
    if sort == "newest":
        order = [lead_date.desc()]
    elif sort == "oldest":
        order = [lead_date.asc()]
    elif sort == "name":
        order = [TeleCallLead.full_name.asc()]
    elif sort == "value":
        order = [TeleCallLead.potential_value.is_(None), TeleCallLead.potential_value.desc()]
    else:  # smart: urgent, then soonest follow-up, then newest
        order = [case((TeleCallLead.is_urgent == True, 0), else_=1),  # noqa: E712
                 TeleCallLead.next_follow_up_at.is_(None), TeleCallLead.next_follow_up_at.asc(),
                 lead_date.desc()]
    leads = (await db.execute(
        select(TeleCallLead).where(final).order_by(*order, TeleCallLead.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    names = await user_names(db, {l.owner_user_id for l in leads})
    fc = await pending_first_calls(db, [l.id for l in leads])

    groups = None
    group_cols = {"owner": TeleCallLead.owner_user_id, "stage": func.coalesce(TeleCallLead.stage, "new"),
                  "status": func.coalesce(TeleCallLead.status, ""), "city": TeleCallLead.sheet_tl_name,
                  "priority": func.coalesce(TeleCallLead.priority, "warm")}
    if group_by in group_cols:
        col = group_cols[group_by]
        grows = (await db.execute(select(col, func.count(TeleCallLead.id)).where(final).group_by(col))).all()
        gnames = await user_names(db, {g for g, _ in grows}) if group_by == "owner" else {}
        groups = []
        for g, c in grows:
            if group_by == "owner":
                label = gnames.get(g, "Unassigned") if g else "Unassigned"
            elif group_by == "stage":
                label = STAGE_LABELS.get(g, g)
            elif group_by == "status":
                label = g or NO_STATUS
            else:
                label = g or "—"
            groups.append({"key": g, "label": label, "count": int(c)})
        groups.sort(key=lambda x: -x["count"])

    return {
        "items": [lead_row(l, names, fc) for l in leads],
        "total": total, "page": page, "page_size": page_size,
        "status_counts": status_counts, "tab_counts": tab_counts, "groups": groups,
    }


class NewLeadRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=3, max_length=30)
    email: str = ""
    city: str
    lead_source: str = "Walk-in"
    phone_model: Optional[str] = None
    service_type: Optional[str] = None
    coverage: Optional[str] = None
    remarks: str = ""
    owner_user_id: Optional[int] = None


@router.post("/leads")
async def create_lead(body: NewLeadRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """+ New lead (walk-in, referral, phone). Lives in the app only — it is
    never written to, or overwritten by, the Google Sheets."""
    scope = await require_scope(db, user)
    valid = [s["tl_name"] for s in TELE_CALL_SHEETS]
    if body.city not in valid:
        raise HTTPException(status_code=400, detail=f"City must be one of {valid}")
    if not scope.is_admin and body.city not in scope.sheets:
        raise HTTPException(status_code=403, detail="You can only add leads for your own city")
    automation = await get_automation(db)
    go_live, _ = await ensure_go_live(db)
    now = utcnow()
    lead = TeleCallLead(
        sheet_tl_name=body.city, spreadsheet_id="", full_name=body.full_name.strip(),
        phone=body.phone.strip(), email=body.email.strip(), lead_source=body.lead_source.strip() or "Walk-in",
        created_time=to_ist(now).strftime("%Y-%m-%d %H:%M"), submitted_at=now, created_at=now,
        status="", remarks=body.remarks, phone_model=body.phone_model, service_type=body.service_type,
        coverage=body.coverage, person_calling="", edited_by_user=True,
    )
    refresh_derived(lead)
    db.add(lead)
    await db.flush()
    await refresh_potential_value(db, lead)
    add_activity(db, lead, "system", user_id=user.id, notes=f"Lead created in the app ({lead.lead_source})", at=now)

    owner_id = None
    source = "manual"
    if body.owner_user_id and scope.can_reassign:
        owner_id = body.owner_user_id
    elif scope.is_telecaller or scope.is_salesperson:
        owner_id = user.id
    elif automation.get("auto_assign", True):
        chosen = await RoundRobin(db, now).pick(body.city)
        if chosen:
            owner_id, source = chosen["id"], "auto"
    if owner_id:
        await transfer_ownership(db, lead, owner_id, source=source, actor_id=user.id, now=now,
                                 automation=automation, reason="New lead")
        due = add_working_minutes(now, automation["first_call_minutes"], automation["working_hours"])
        create_followup(db, lead, kind="first_call", due_at=due, owner_id=owner_id, created_by=user.id,
                        reason="First call for a new lead", at=now)
    await db.commit()
    names = await user_names(db, [lead.owner_user_id])
    return {"ok": True, "lead": lead_row(lead, names, await pending_first_calls(db, [lead.id]))}


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    lead = await load_lead(db, lead_id, scope)
    acts = (await db.execute(
        select(TeleLeadActivity).where(TeleLeadActivity.lead_id == lead.id)
        .order_by(TeleLeadActivity.created_at.desc(), TeleLeadActivity.id.desc()).limit(200)
    )).scalars().all()
    fus = (await db.execute(
        select(TeleLeadFollowup).where(TeleLeadFollowup.lead_id == lead.id)
        .order_by(TeleLeadFollowup.due_at.desc()).limit(50)
    )).scalars().all()
    appts = (await db.execute(
        select(TeleAppointment).where(TeleAppointment.lead_id == lead.id).order_by(TeleAppointment.scheduled_at.desc())
    )).scalars().all()
    names = await user_names(db, {lead.owner_user_id} | {a.user_id for a in acts}
                             | {f.owner_user_id for f in fus} | {f.completed_by for f in fus})
    fc = await pending_first_calls(db, [lead.id])

    # Milestones first (Meta submitted → received → …), then the log.
    timeline = []
    if lead.submitted_at:
        timeline.append({"at": iso_utc(lead.submitted_at), "type": "milestone", "label": "Submitted on Meta"})
    if lead.created_at:
        timeline.append({"at": iso_utc(lead.created_at), "type": "milestone", "label": "Received by the CRM"})
    for a in acts:
        timeline.append({
            "id": a.id, "at": iso_utc(a.created_at), "type": a.type, "outcome": a.outcome,
            "outcome_label": OUTCOMES.get(a.outcome or "", {}).get("label"),
            "old_value": a.old_value, "new_value": a.new_value, "notes": a.notes,
            "user": names.get(a.user_id) if a.user_id else "System", "meta": a.meta,
        })
    timeline.sort(key=lambda x: x["at"] or "", reverse=True)
    return {
        "lead": lead_row(lead, names, fc),
        "timeline": timeline,
        "followups": [{
            "id": f.id, "kind": f.kind, "due_at": iso_utc(f.due_at), "status": f.status,
            "owner_name": names.get(f.owner_user_id), "owner_user_id": f.owner_user_id,
            "completed_at": iso_utc(f.completed_at), "completed_by": names.get(f.completed_by),
            "outcome": f.outcome, "reason": f.reason, "attempt_no": f.attempt_no,
        } for f in fus],
        "appointments": [{
            "id": a.id, "scheduled_at": iso_utc(a.scheduled_at), "purpose": a.purpose,
            "attendance": a.attendance, "store_id": a.store_id, "source": a.source,
        } for a in appts],
    }


class LeadPatch(BaseModel):
    stage: Optional[str] = None
    priority: Optional[str] = None          # hot | warm | cold | auto
    phone_model: Optional[str] = None
    service_type: Optional[str] = None
    coverage: Optional[str] = None
    remarks: Optional[str] = None
    next_follow_up_at: Optional[str] = None  # ISO; "" clears nothing — use activities


@router.patch("/leads/{lead_id}")
async def patch_lead(lead_id: int, body: LeadPatch, db: AsyncSession = Depends(get_db),
                     user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    lead = await load_lead(db, lead_id, scope)
    now = utcnow()
    changes: dict = {}

    if body.stage is not None:
        if body.stage not in STAGE_KEYS:
            raise HTTPException(status_code=400, detail=f"stage must be one of {STAGE_KEYS}")
        if body.stage != (lead.stage or "new"):
            changes["stage"] = [lead.stage, body.stage]
            add_activity(db, lead, "stage_change", user_id=user.id,
                         old_value=STAGE_LABELS.get(lead.stage or "new"), new_value=STAGE_LABELS[body.stage], at=now)
            lead.stage = body.stage  # a manual choice wins over the status-derived stage
            lead.stage_manual = True
            lead.priority = derive_priority(lead.stage, lead.priority, bool(lead.priority_manual))
    if body.priority is not None:
        if body.priority == "auto":
            lead.priority_manual = False
            refresh_derived(lead)
        elif body.priority in PRIORITIES:
            if body.priority != lead.priority:
                changes["priority"] = [lead.priority, body.priority]
                add_activity(db, lead, "note", user_id=user.id, old_value=lead.priority,
                             new_value=body.priority, notes="Priority changed", at=now)
            lead.priority = body.priority
            lead.priority_manual = True
        else:
            raise HTTPException(status_code=400, detail="priority must be hot, warm, cold or auto")

    device_changed = False
    for field in ("phone_model", "service_type", "coverage"):
        value = getattr(body, field)
        if value is not None and value != (getattr(lead, field) or ""):
            setattr(lead, field, value.strip() or None)
            device_changed = True
    if device_changed:
        await refresh_potential_value(db, lead)
        changes["device"] = [None, f"{lead.phone_model} · {lead.service_type} · {lead.coverage}"]
        add_activity(db, lead, "note", user_id=user.id, notes="Device details updated",
                     new_value=f"{lead.phone_model or '—'} · {lead.service_type or '—'} · {lead.coverage or 'Standard'}",
                     at=now)
    if body.remarks is not None and body.remarks != (lead.remarks or ""):
        lead.remarks = body.remarks
        mark_edited(lead, "remarks")
        lead.edited_by_user = True

    if body.next_follow_up_at:
        due = parse_client_datetime(body.next_follow_up_at)
        if not due:
            raise HTTPException(status_code=400, detail="next_follow_up_at must be an ISO date-time")
        # Moving a follow-up closes the old one as "rescheduled" (counted as
        # missed if it was already overdue) and opens the new time.
        open_fus = (await db.execute(
            select(TeleLeadFollowup).where(TeleLeadFollowup.lead_id == lead.id, TeleLeadFollowup.status == "open",
                                           TeleLeadFollowup.kind != "first_call")
        )).scalars().all()
        for f in open_fus:
            f.status = "rescheduled"
            f.completed_at = now
            f.completed_by = user.id
        await resolve_alerts_for_followups(db, [f.id for f in open_fus], now)
        create_followup(db, lead, kind="call", due_at=due, owner_id=lead.owner_user_id or user.id,
                        created_by=user.id, reason="Follow-up scheduled", at=now)
        add_activity(db, lead, "note", user_id=user.id, notes="Next follow-up scheduled",
                     new_value=to_ist(due).strftime("%d %b %Y %H:%M"), at=now)
        await recompute_next_follow_up(db, lead)

    if changes and (scope.is_admin or scope.is_tl):
        record_audit(db, user.id, "lead_update", "tele_call_lead", lead.id,
                     before={k: v[0] for k, v in changes.items()}, after={k: v[1] for k, v in changes.items()})
    await db.commit()
    names = await user_names(db, [lead.owner_user_id])
    return {"ok": True, "lead": lead_row(lead, names, await pending_first_calls(db, [lead.id]))}


class ActivityRequest(BaseModel):
    outcome: str
    notes: Optional[str] = None
    callback_at: Optional[str] = None
    next_follow_up_at: Optional[str] = None
    appointment_at: Optional[str] = None
    appointment_purpose: Optional[str] = None
    store_id: Optional[int] = None
    sale_amount: Optional[str] = None


@router.post("/leads/{lead_id}/activities")
async def log_activity(lead_id: int, body: ActivityRequest, db: AsyncSession = Depends(get_db),
                       user=Depends(get_current_user)):
    """Log activity: record the call outcome; the system sets the status and
    schedules the next step (see services/crm/engine.py next_step_for_outcome)."""
    scope = await require_scope(db, user)
    lead = await load_lead(db, lead_id, scope)
    if body.outcome not in OUTCOMES:
        raise HTTPException(status_code=400, detail=f"outcome must be one of {list(OUTCOMES)}")
    if body.outcome == "callback_requested" and not body.callback_at:
        raise HTTPException(status_code=400, detail="Pick the time the customer asked to be called back")
    if body.outcome == "appointment_booked" and not body.appointment_at:
        raise HTTPException(status_code=400, detail="Pick the appointment date and time")
    automation = await get_automation(db)
    result = await log_outcome(
        db, lead, user, body.outcome, automation=automation, notes=body.notes,
        callback_at=parse_client_datetime(body.callback_at),
        next_follow_up_at=parse_client_datetime(body.next_follow_up_at),
        appointment_at=parse_client_datetime(body.appointment_at),
        appointment_purpose=body.appointment_purpose, store_id=body.store_id,
        sale_amount=body.sale_amount, actor_role=scope.role,
    )
    await db.commit()
    names = await user_names(db, [lead.owner_user_id])
    fu = result["followup"]
    return {
        "ok": True,
        "lead": lead_row(lead, names, await pending_first_calls(db, [lead.id])),
        "next_follow_up": {"due_at": iso_utc(fu.due_at), "kind": fu.kind, "reason": fu.reason} if fu else None,
    }


class AssignRequest(BaseModel):
    owner_user_id: Optional[int] = None  # None = unassign


async def _assign(db: AsyncSession, scope: CrmScope, user: User, lead: TeleCallLead, owner_id: int | None,
                  automation: dict, now: datetime) -> bool:
    if owner_id is not None:
        members = await sheet_members(db, None if scope.is_admin else scope.sheets)
        allowed = {m["id"] for m in members if scope.is_admin or lead.sheet_tl_name in m["sheets"]}
        if owner_id not in allowed:
            raise HTTPException(status_code=400, detail="That person is not on this lead's city team")
    before = lead.owner_user_id
    changed = await transfer_ownership(db, lead, owner_id, source="manual", actor_id=user.id, now=now,
                                       automation=automation, reason=f"Reassigned by {user.name}")
    if changed:
        record_audit(db, user.id, "reassign", "tele_call_lead", lead.id,
                     before={"owner_user_id": before}, after={"owner_user_id": owner_id})
    return changed


@router.post("/leads/{lead_id}/assign")
async def assign_lead(lead_id: int, body: AssignRequest, db: AsyncSession = Depends(get_db),
                      user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    if not scope.can_reassign:
        raise HTTPException(status_code=403, detail="Only team leaders and admins can reassign leads")
    lead = await load_lead(db, lead_id, scope)
    await _assign(db, scope, user, lead, body.owner_user_id, await get_automation(db), utcnow())
    await db.commit()
    names = await user_names(db, [lead.owner_user_id])
    return {"ok": True, "lead": lead_row(lead, names, await pending_first_calls(db, [lead.id]))}


class BulkAssignRequest(BaseModel):
    lead_ids: list[int]
    owner_user_id: Optional[int] = None


@router.post("/leads/bulk-assign")
async def bulk_assign(body: BulkAssignRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    if not scope.can_reassign:
        raise HTTPException(status_code=403, detail="Only team leaders and admins can reassign leads")
    if not body.lead_ids or len(body.lead_ids) > 500:
        raise HTTPException(status_code=400, detail="Select between 1 and 500 leads")
    automation = await get_automation(db)
    now = utcnow()
    leads = (await db.execute(select(TeleCallLead).where(TeleCallLead.id.in_(body.lead_ids)))).scalars().all()
    changed = 0
    skipped = 0
    for lead in leads:
        if not lead_in_scope(lead, scope):
            skipped += 1
            continue
        try:
            if await _assign(db, scope, user, lead, body.owner_user_id, automation, now):
                changed += 1
        except HTTPException:
            skipped += 1
    await db.commit()
    return {"ok": True, "changed": changed, "skipped": skipped}


# ── overview (Today) ───────────────────────────────────────────────
async def _followup_rows(db: AsyncSession, scope: CrmScope, *, owner_id: int | None, where_extra,
                         limit: int, order) -> list[dict]:
    q = (select(TeleLeadFollowup, TeleCallLead)
         .join(TeleCallLead, TeleCallLead.id == TeleLeadFollowup.lead_id)
         .where(lead_filter(scope), TeleLeadFollowup.status == "open", where_extra))
    if owner_id is not None:
        q = q.where(TeleLeadFollowup.owner_user_id == owner_id)
    rows = (await db.execute(q.order_by(*order).limit(limit))).all()
    names = await user_names(db, {f.owner_user_id for f, _ in rows})
    now = utcnow()
    return [{
        "id": f.id, "kind": f.kind, "due_at": iso_utc(f.due_at), "reason": f.reason,
        "overdue": f.due_at < now, "attempt_no": f.attempt_no,
        "owner_user_id": f.owner_user_id, "owner_name": names.get(f.owner_user_id),
        "lead": {"id": l.id, "full_name": l.full_name, "phone": l.phone, "city": l.sheet_tl_name,
                 "status": l.status or "", "status_label": l.status or NO_STATUS,
                 "stage": l.stage or "new", "priority": l.priority or "warm",
                 "phone_model": l.phone_model, "service_type": l.service_type, "is_urgent": bool(l.is_urgent)},
    } for f, l in rows]


def _mine_default(scope: CrmScope, mine: str) -> bool:
    if mine in ("1", "true"):
        return True
    if mine in ("0", "false"):
        return False
    return scope.is_telecaller or scope.is_salesperson


@router.get("/overview")
async def overview(mine: str = Query(""), db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    now = utcnow()
    only_mine = _mine_default(scope, mine)
    owner_id = user.id if only_mine else None
    base = lead_filter(scope)
    owned = and_(base, TeleCallLead.owner_user_id == user.id) if only_mine else base

    tiles = await crm_metrics.queue_counts(db, base, now=now, owner_id=owner_id)

    alerts = (await db.execute(
        select(CrmAlert).where(CrmAlert.recipient_user_id == user.id, CrmAlert.resolved_at.is_(None))
        .order_by(CrmAlert.level.desc(), CrmAlert.created_at.desc()).limit(6)
    )).scalars().all()
    alert_total = int((await db.execute(
        select(func.count(CrmAlert.id)).where(CrmAlert.recipient_user_id == user.id, CrmAlert.resolved_at.is_(None))
    )).scalar() or 0)
    alert_leads = await _lead_names(db, {a.lead_id for a in alerts})

    followups = await _followup_rows(
        db, scope, owner_id=owner_id, where_extra=true(), limit=8,
        order=[TeleLeadFollowup.due_at.asc()],
    )

    # sales snapshot
    open_stage = func.coalesce(TeleCallLead.stage, "new").notin_(list(CLOSED_STAGES))
    open_value = float((await db.execute(
        select(func.coalesce(func.sum(TeleCallLead.potential_value), 0)).where(owned, open_stage)
    )).scalar() or 0)
    today = ist_today(now)
    month_start, _ = ist_day_bounds_utc(today.replace(day=1))
    conv_rows = (await db.execute(
        select(TeleCallLead.sale_amount).where(
            owned, TeleCallLead.status == "Sale Conversion",
            func.coalesce(TeleCallLead.last_contact_at, TeleCallLead.submitted_at, TeleCallLead.created_at) >= month_start,
        )
    )).scalars().all()
    appts_today = await _appointments_between(db, scope, today, today + timedelta(days=1), owner_id)

    # pipeline by stage
    stage_rows = (await db.execute(
        select(func.coalesce(TeleCallLead.stage, "new"), func.count(TeleCallLead.id),
               func.coalesce(func.sum(TeleCallLead.potential_value), 0))
        .where(owned).group_by(func.coalesce(TeleCallLead.stage, "new"))
    )).all()
    by_stage = {s: (int(c), float(v)) for s, c, v in stage_rows}

    health = await _data_health_counts(db, base, now)
    return {
        "mine": only_mine,
        "tiles": tiles,
        "inbox": {"total": alert_total, "items": [
            {**alert_to_dict(a), "lead_name": alert_leads.get(a.lead_id)} for a in alerts]},
        "followups": followups,
        "sales": {
            "open_pipeline_value": open_value,
            "converted_this_month_value": sum(parse_amount(v) for v in conv_rows),
            "converted_this_month_count": len(conv_rows),
            "appointments_today": len(appts_today),
        },
        "pipeline": [{"stage": s["key"], "label": s["label"], "count": by_stage.get(s["key"], (0, 0))[0],
                      "value": by_stage.get(s["key"], (0, 0.0))[1]} for s in STAGES],
        "data_health": health,
    }


async def _lead_names(db: AsyncSession, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(TeleCallLead.id, TeleCallLead.full_name).where(TeleCallLead.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


async def _data_health_counts(db: AsyncSession, base, now: datetime) -> dict:
    open_stage = func.coalesce(TeleCallLead.stage, "new").notin_(list(CLOSED_STAGES))
    async def count(*conds):
        return int((await db.execute(select(func.count(TeleCallLead.id)).where(base, *conds))).scalar() or 0)
    return {
        "missing_phone": await count(func.coalesce(TeleCallLead.phone, "") == ""),
        "no_status_24h": await count(func.coalesce(TeleCallLead.status, "") == "",
                                     crm_metrics.lead_date_col() < now - timedelta(hours=24)),
        "unassigned_open": await count(TeleCallLead.owner_user_id.is_(None), open_stage),
        "missing_model": await count(TeleCallLead.phone_model.is_(None), open_stage),
        "unknown_status": await count(func.coalesce(TeleCallLead.status, "") != "",
                                      TeleCallLead.status.notin_(STATUSES)),
    }


# ── follow-ups (Tasks) ─────────────────────────────────────────────
@router.get("/followups")
async def list_followups(bucket: str = Query("all"), mine: str = Query(""), owner: str = Query(""),
                         db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    now = utcnow()
    owner_id = user.id if _mine_default(scope, mine) else None
    if owner.isdigit() and scope.can_reassign:
        owner_id = int(owner)
    day_start, day_end = ist_day_bounds_utc(ist_today(now))
    buckets = {
        "overdue": TeleLeadFollowup.due_at < now,
        "today": and_(TeleLeadFollowup.due_at >= now, TeleLeadFollowup.due_at < day_end),
        "upcoming": TeleLeadFollowup.due_at >= day_end,
    }
    out = {}
    for name, clause in buckets.items():
        if bucket not in ("all", name):
            continue
        out[name] = await _followup_rows(db, scope, owner_id=owner_id, where_extra=clause,
                                         limit=200 if name != "upcoming" else 100,
                                         order=[TeleLeadFollowup.due_at.asc()])
    return {"mine": owner_id == user.id, "owner_id": owner_id, **out}


class CompleteRequest(BaseModel):
    notes: Optional[str] = None


@router.post("/followups/{followup_id}/complete")
async def complete_followup(followup_id: int, body: CompleteRequest, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    """Mark a follow-up done without a call outcome (e.g. handled in store).
    Prefer Log activity, which also records the outcome and next step."""
    scope = await require_scope(db, user)
    fu = (await db.execute(select(TeleLeadFollowup).where(TeleLeadFollowup.id == followup_id))).scalar_one_or_none()
    if not fu:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    lead = await load_lead(db, fu.lead_id, scope)
    if fu.status != "open":
        return {"ok": True, "already": fu.status}
    now = utcnow()
    fu.status = "done"
    fu.completed_at = now
    fu.completed_by = user.id
    fu.outcome = "marked_done"
    await resolve_alerts_for_followups(db, [fu.id], now)
    add_activity(db, lead, "note", user_id=user.id, notes=body.notes or "Follow-up marked done", at=now)
    await recompute_next_follow_up(db, lead)
    await db.commit()
    return {"ok": True}


# ── appointments ───────────────────────────────────────────────────
async def _appointments_between(db: AsyncSession, scope: CrmScope, d_from: date, d_to: date,
                                owner_id: int | None) -> list[dict]:
    """App appointments plus sheet 'Appointment Date' values (marked
    source='sheet') for leads that have no app appointment that day."""
    s_utc, _ = ist_day_bounds_utc(d_from)
    e_utc, _ = ist_day_bounds_utc(d_to)
    q = (select(TeleAppointment, TeleCallLead).join(TeleCallLead, TeleCallLead.id == TeleAppointment.lead_id)
         .where(lead_filter(scope), TeleAppointment.scheduled_at >= s_utc, TeleAppointment.scheduled_at < e_utc))
    if owner_id is not None:
        q = q.where(TeleCallLead.owner_user_id == owner_id)
    rows = (await db.execute(q.order_by(TeleAppointment.scheduled_at))).all()
    names = await user_names(db, {l.owner_user_id for _, l in rows})
    out = []
    have = set()
    for a, l in rows:
        day = to_ist(a.scheduled_at).date()
        have.add((l.id, day))
        out.append({
            "id": a.id, "lead_id": l.id, "lead_name": l.full_name, "phone": l.phone, "city": l.sheet_tl_name,
            "scheduled_at": iso_utc(a.scheduled_at), "date": day.isoformat(), "has_time": True,
            "purpose": a.purpose, "attendance": a.attendance, "source": a.source, "store_id": a.store_id,
            "owner_name": names.get(l.owner_user_id),
        })

    # Sheet appointment dates (text) — parse and keep those in range.
    sq = select(TeleCallLead).where(lead_filter(scope), func.coalesce(TeleCallLead.appointment_date, "") != "")
    if owner_id is not None:
        sq = sq.where(TeleCallLead.owner_user_id == owner_id)
    sheet_leads = (await db.execute(sq)).scalars().all()
    more_names = await user_names(db, {l.owner_user_id for l in sheet_leads} - set(names))
    names.update(more_names)
    for l in sheet_leads:
        dt = parse_sheet_datetime(l.appointment_date)
        if not dt:
            continue
        local = to_ist(dt)
        day = local.date()
        if not (d_from <= day < d_to) or (l.id, day) in have:
            continue
        has_time = not (local.hour == 0 and local.minute == 0)
        out.append({
            "id": None, "lead_id": l.id, "lead_name": l.full_name, "phone": l.phone, "city": l.sheet_tl_name,
            "scheduled_at": iso_utc(dt), "date": day.isoformat(), "has_time": has_time,
            "purpose": l.service_type or l.product or "Store visit", "attendance": "scheduled",
            "source": "sheet", "store_id": None, "owner_name": names.get(l.owner_user_id),
        })
    out.sort(key=lambda x: (x["date"], x["scheduled_at"] or ""))
    return out


@router.get("/appointments")
async def list_appointments(start: str = Query(""), days: int = Query(3, ge=1, le=31), mine: str = Query(""),
                            db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    try:
        d_from = date.fromisoformat(start) if start else ist_today()
    except ValueError:
        raise HTTPException(status_code=400, detail="start must be YYYY-MM-DD")
    owner_id = user.id if _mine_default(scope, mine) else None
    items = await _appointments_between(db, scope, d_from, d_from + timedelta(days=days), owner_id)
    by_day = defaultdict(list)
    for it in items:
        by_day[it["date"]].append(it)
    return {
        "start": d_from.isoformat(), "days": days, "mine": owner_id is not None,
        "columns": [{"date": (d_from + timedelta(days=i)).isoformat(),
                     "items": by_day.get((d_from + timedelta(days=i)).isoformat(), [])} for i in range(days)],
    }


class AppointmentRequest(BaseModel):
    lead_id: int
    scheduled_at: str
    purpose: Optional[str] = None
    store_id: Optional[int] = None
    attendance: str = "scheduled"


ATTENDANCE = ["scheduled", "attended", "no_show", "rescheduled", "cancelled"]


@router.post("/appointments")
async def create_appointment(body: AppointmentRequest, db: AsyncSession = Depends(get_db),
                             user=Depends(get_current_user)):
    """Book an appointment (or turn a sheet appointment into an app record).
    Also fills the lead's Appointment Date text so existing views count it."""
    scope = await require_scope(db, user)
    lead = await load_lead(db, body.lead_id, scope)
    when = parse_client_datetime(body.scheduled_at)
    if not when:
        raise HTTPException(status_code=400, detail="scheduled_at must be an ISO date-time")
    if body.attendance not in ATTENDANCE:
        raise HTTPException(status_code=400, detail=f"attendance must be one of {ATTENDANCE}")
    now = utcnow()
    appt = TeleAppointment(lead_id=lead.id, scheduled_at=when, purpose=body.purpose or lead.service_type or "Store visit",
                           store_id=body.store_id, attendance=body.attendance, source="app",
                           created_by=user.id, created_at=now)
    db.add(appt)
    lead.appointment_date = to_ist(when).date().isoformat()
    mark_edited(lead, "appointment_date")
    lead.edited_by_user = True
    upcoming = body.attendance == "scheduled" and when > now
    if upcoming and (not lead.status or lead.status in ("Call Not Connected", "Call back later", "Unattended", "Will Visit")):
        old = lead.status or ""
        lead.status = "Appointment"
        mark_edited(lead, "status")
        refresh_derived(lead)
        add_activity(db, lead, "status_change", user_id=user.id, old_value=old or NO_STATUS,
                     new_value="Appointment", at=now)
    add_activity(db, lead, "appointment", user_id=user.id, new_value=to_ist(when).strftime("%d %b %Y %H:%M"),
                 notes=appt.purpose, at=now)
    if upcoming:
        confirm = max(when - timedelta(hours=2), now)
        create_followup(db, lead, kind="appointment_confirm", due_at=confirm,
                        owner_id=lead.owner_user_id or user.id, created_by=user.id,
                        reason="Confirm the appointment", at=now)
    elif body.attendance == "no_show":
        automation = await get_automation(db)
        create_followup(db, lead, kind="call", due_at=add_working_minutes(now, 30, automation["working_hours"]),
                        owner_id=lead.owner_user_id or user.id, created_by=user.id,
                        reason="Customer missed the appointment — call to reschedule", at=now)
    await db.commit()
    return {"ok": True, "id": appt.id}


class AppointmentPatch(BaseModel):
    attendance: Optional[str] = None
    scheduled_at: Optional[str] = None
    purpose: Optional[str] = None


@router.patch("/appointments/{appointment_id}")
async def patch_appointment(appointment_id: int, body: AppointmentPatch, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    appt = (await db.execute(select(TeleAppointment).where(TeleAppointment.id == appointment_id))).scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    lead = await load_lead(db, appt.lead_id, scope)
    now = utcnow()
    if body.attendance is not None:
        if body.attendance not in ATTENDANCE:
            raise HTTPException(status_code=400, detail=f"attendance must be one of {ATTENDANCE}")
        if body.attendance != appt.attendance:
            add_activity(db, lead, "appointment", user_id=user.id, old_value=appt.attendance,
                         new_value=body.attendance, notes="Attendance updated", at=now)
            appt.attendance = body.attendance
            if body.attendance == "no_show":
                # Missed visit: follow up (mockup: "follow up on missed visits").
                automation = await get_automation(db)
                create_followup(db, lead, kind="call",
                                due_at=add_working_minutes(now, 30, automation["working_hours"]),
                                owner_id=lead.owner_user_id or user.id, created_by=user.id,
                                reason="Customer missed the appointment — call to reschedule", at=now)
    if body.scheduled_at:
        when = parse_client_datetime(body.scheduled_at)
        if not when:
            raise HTTPException(status_code=400, detail="scheduled_at must be an ISO date-time")
        add_activity(db, lead, "appointment", user_id=user.id, old_value=to_ist(appt.scheduled_at).strftime("%d %b %H:%M"),
                     new_value=to_ist(when).strftime("%d %b %H:%M"), notes="Appointment moved", at=now)
        appt.scheduled_at = when
        lead.appointment_date = to_ist(when).date().isoformat()
        mark_edited(lead, "appointment_date")
    if body.purpose is not None:
        appt.purpose = body.purpose
    await db.commit()
    return {"ok": True}


# ── pipeline ───────────────────────────────────────────────────────
@router.get("/pipeline")
async def pipeline(mine: str = Query("0"), sheet: str = Query(""), owner: str = Query(""), q: str = Query(""),
                   per_stage: int = Query(50, ge=1, le=200),
                   db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    extra = filters_clause(status="", stage="", owner="me" if mine in ("1", "true") else owner, sheet=sheet,
                           priority="", q=q, user_id=user.id)
    base = and_(lead_filter(scope), extra) if extra is not None else lead_filter(scope)
    stage_col = func.coalesce(TeleCallLead.stage, "new")
    totals = (await db.execute(
        select(stage_col, func.count(TeleCallLead.id)).where(base).group_by(stage_col)
    )).all()
    count_by = {s: int(c) for s, c in totals}
    columns = []
    for st in STAGES:
        leads = (await db.execute(
            select(TeleCallLead).where(base, stage_col == st["key"])
            .order_by(TeleCallLead.next_follow_up_at.is_(None), TeleCallLead.next_follow_up_at.asc(),
                      crm_metrics.lead_date_col().desc())
            .limit(per_stage)
        )).scalars().all()
        # stage value: converted leads count their sale amount, others the price-book value
        all_vals = (await db.execute(
            select(TeleCallLead.potential_value, TeleCallLead.sale_amount).where(base, stage_col == st["key"])
        )).all()
        if st["key"] == "converted":
            value = sum(parse_amount(sa) or float(pv or 0) for pv, sa in all_vals)
        else:
            value = sum(float(pv or 0) for pv, _ in all_vals)
        names = await user_names(db, {l.owner_user_id for l in leads})
        columns.append({
            "stage": st["key"], "label": st["label"], "count": count_by.get(st["key"], 0), "value": value,
            "cards": [lead_row(l, names) for l in leads],
        })
    return {"columns": columns}


# ── alerts ─────────────────────────────────────────────────────────
@router.get("/alerts")
async def list_alerts(state: str = Query("open"), db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    await require_scope(db, user)
    q = select(CrmAlert).where(CrmAlert.recipient_user_id == user.id)
    if state == "open":
        q = q.where(CrmAlert.resolved_at.is_(None))
    alerts = (await db.execute(q.order_by(CrmAlert.resolved_at.is_(None).desc(), CrmAlert.level.desc(),
                                          CrmAlert.created_at.desc()).limit(200))).scalars().all()
    leads = await _lead_names(db, {a.lead_id for a in alerts})
    items = [{**alert_to_dict(a), "lead_name": leads.get(a.lead_id)} for a in alerts]
    return {
        "lead_alerts": [a for a in items if a["kind"] not in ("weekly_review", "coaching")],
        "performance": [a for a in items if a["kind"] in ("weekly_review", "coaching")],
        "open_count": sum(1 for a in items if not a["resolved_at"]),
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Acknowledge ≠ resolve: operational alerts clear only when the
    underlying follow-up is handled. Coaching/review notes resolve here."""
    alert = (await db.execute(select(CrmAlert).where(CrmAlert.id == alert_id))).scalar_one_or_none()
    if not alert or alert.recipient_user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert not found")
    now = utcnow()
    alert.acknowledged_at = alert.acknowledged_at or now
    alert.acknowledged_by = user.id
    if alert.kind in ("coaching", "reassigned_to_you") and not alert.resolved_at:
        alert.resolved_at = now
    await db.commit()
    return {"ok": True, "alert": alert_to_dict(alert)}


# ── saved views ────────────────────────────────────────────────────
class SavedViewRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    page: str = "leads"
    filters: dict = {}
    columns: list[str] = []


@router.get("/views")
async def list_views(page: str = Query("leads"), db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(select(CrmSavedView).where(CrmSavedView.user_id == user.id, CrmSavedView.page == page)
                             .order_by(CrmSavedView.name))).scalars().all()
    return {"views": [{"id": v.id, "name": v.name, "filters": v.filters or {}, "columns": v.columns or []} for v in rows]}


@router.post("/views")
async def save_view(body: SavedViewRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    existing = (await db.execute(select(CrmSavedView).where(
        CrmSavedView.user_id == user.id, CrmSavedView.page == body.page, CrmSavedView.name == body.name,
    ))).scalar_one_or_none()
    if existing:
        existing.filters, existing.columns = body.filters, body.columns
        view = existing
    else:
        view = CrmSavedView(user_id=user.id, page=body.page, name=body.name, filters=body.filters,
                            columns=body.columns, created_at=utcnow())
        db.add(view)
    await db.commit()
    return {"ok": True, "id": view.id}


@router.delete("/views/{view_id}")
async def delete_view(view_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    view = (await db.execute(select(CrmSavedView).where(CrmSavedView.id == view_id))).scalar_one_or_none()
    if not view or view.user_id != user.id:
        raise HTTPException(status_code=404, detail="View not found")
    await db.delete(view)
    await db.commit()
    return {"ok": True}


# ── availability ───────────────────────────────────────────────────
class AvailabilityRequest(BaseModel):
    available: bool


@router.put("/me/availability")
async def set_my_availability(body: AvailabilityRequest, db: AsyncSession = Depends(get_db),
                              user=Depends(get_current_user)):
    """Available / Away. Away agents are skipped by automatic assignment."""
    user.available_for_leads = body.available
    await db.commit()
    return {"ok": True, "available": body.available}


@router.get("/team")
async def team(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    agents = await visible_agents(db, scope)
    ids = [a["id"] for a in agents]
    open_stage = func.coalesce(TeleCallLead.stage, "new").notin_(list(CLOSED_STAGES))
    counts = dict((await db.execute(
        select(TeleCallLead.owner_user_id, func.count(TeleCallLead.id))
        .where(TeleCallLead.owner_user_id.in_(ids), open_stage).group_by(TeleCallLead.owner_user_id)
    )).all()) if ids else {}
    return {"agents": [{**a, "open_leads": int(counts.get(a["id"], 0))} for a in agents],
            "can_change": scope.can_reassign}


@router.put("/team/{user_id}/availability")
async def set_agent_availability(user_id: int, body: AvailabilityRequest, db: AsyncSession = Depends(get_db),
                                 user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    if user_id != user.id:
        if not scope.can_reassign:
            raise HTTPException(status_code=403, detail="Only team leaders and admins can change others")
        if user_id not in {a["id"] for a in await visible_agents(db, scope)}:
            raise HTTPException(status_code=403, detail="Not on your team")
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.available_for_leads = body.available
    await db.commit()
    return {"ok": True}
