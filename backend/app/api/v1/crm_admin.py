"""Telecalling CRM — reports, automation settings, price book and the CRM
settings tabs (integrations, data quality, audit history)."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_user_permissions
from ...db.session import get_db
from ...models.models import (
    AuditLog, CrmAlert, PriceBookEntry, TeleCallLead, TeleLeadActivity, TeleLeadFollowup, User,
)
from ...services.crm import metrics as crm_metrics
from ...services.crm.config import (
    get_aliases, get_automation, get_go_live, get_targets, save_aliases, save_automation, save_targets,
)
from ...services.crm.engine import (
    add_activity, create_alert, emit_alerts, norm_name, norm_phone, record_audit, user_names,
)
from ...services.crm.scope import CrmScope, get_scope, lead_filter, sheet_members, visible_agents
from ...services.crm.status import CLOSED_STAGES, NO_STATUS, STAGE_LABELS, STATUSES
from ...services.crm.timeutil import ist_today, iso_utc, to_ist, utcnow
from ...services.tele_call_sync import LAST_SYNC, TELE_CALL_SHEETS

router = APIRouter(prefix="/crm", tags=["Telecalling CRM"])


async def _scope(db: AsyncSession, user: User) -> CrmScope:
    scope = await get_scope(db, user)
    if not scope.has_access:
        raise HTTPException(status_code=403, detail="Your role has no access to telecalling leads")
    return scope


async def _has_perm(db: AsyncSession, user: User, resource: str, action: str) -> bool:
    return any(p["resource"] == resource and p["action"] == action for p in await get_user_permissions(user, db))


def _period(start: str, end: str) -> tuple[date, date]:
    today = ist_today()
    try:
        d_end = date.fromisoformat(end) if end else today
        d_start = date.fromisoformat(start) if start else d_end - timedelta(days=d_end.weekday())
    except ValueError:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD")
    if d_start > d_end:
        raise HTTPException(status_code=400, detail="start must be on or before end")
    return d_start, d_end


# ── reports ────────────────────────────────────────────────────────
@router.get("/reports/agents")
async def agents_report(start: str = Query(""), end: str = Query(""), sheet: str = Query(""),
                        agent: str = Query(""), db: AsyncSession = Depends(get_db),
                        user=Depends(get_current_user)):
    """Agent performance: a telecaller gets only their own row, a team
    leader their team, admins everyone (optionally one city)."""
    scope = await _scope(db, user)
    d_start, d_end = _period(start, end)
    agents = await visible_agents(db, scope)
    if sheet:
        agents = [a for a in agents if sheet in (a.get("sheets") or [])]
    if agent.isdigit():
        agents = [a for a in agents if a["id"] == int(agent)]
    automation = await get_automation(db)
    targets = await get_targets(db)
    now = utcnow()
    rows = await crm_metrics.agent_report(db, agents, d_start, d_end, now=now, automation=automation,
                                          targets=targets, sheet=sheet or None)
    ps, pe = crm_metrics.previous_period(d_start, d_end)
    return {
        "period": {"start": d_start.isoformat(), "end": d_end.isoformat()},
        "previous_period": {"start": ps.isoformat(), "end": pe.isoformat()},
        "targets": targets,
        "first_call_minutes": automation["first_call_minutes"],
        "rows": rows,
        "can_coach": scope.can_reassign,
        "sheets": scope.sheets if not scope.is_admin else [s["tl_name"] for s in TELE_CALL_SHEETS],
        "go_live": iso_utc(await get_go_live(db)),
    }


class CoachRequest(BaseModel):
    user_id: int
    note: str


@router.post("/reports/coach")
async def coach(body: CoachRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Send a coaching note to an agent. It also closes the weekly review
    notifications about that agent that were sent to you."""
    scope = await _scope(db, user)
    if not scope.can_reassign:
        raise HTTPException(status_code=403, detail="Only team leaders and admins can coach")
    if body.user_id not in {a["id"] for a in await visible_agents(db, scope)}:
        raise HTTPException(status_code=403, detail="Not on your team")
    if not body.note.strip():
        raise HTTPException(status_code=400, detail="Write a short coaching note")
    now = utcnow()
    created: list = []
    await create_alert(db, recipient_id=body.user_id, kind="coaching", level=1,
                       title=f"Coaching note from {user.name}", body=body.note.strip(),
                       dedupe_key=f"coach:{body.user_id}:{user.id}:{now.isoformat()}", out=created)
    reviews = (await db.execute(
        select(CrmAlert).where(CrmAlert.recipient_user_id == user.id, CrmAlert.kind == "weekly_review",
                               CrmAlert.resolved_at.is_(None),
                               CrmAlert.dedupe_key.like(f"weekly:%:{body.user_id}:%"))
    )).scalars().all()
    for r in reviews:
        r.resolved_at = now
        r.acknowledged_at = r.acknowledged_at or now
        r.acknowledged_by = user.id
    record_audit(db, user.id, "coach", "user", body.user_id, after={"note": body.note.strip()[:500]})
    await db.commit()
    await emit_alerts(created)
    return {"ok": True, "resolved_reviews": len(reviews)}


@router.get("/reports/export")
async def export_leads(start: str = Query(""), end: str = Query(""), sheet: str = Query(""),
                       status: str = Query(""), owner: str = Query(""),
                       db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """CSV of leads in your scope. Needs the leads:export permission."""
    scope = await _scope(db, user)
    if not await _has_perm(db, user, "leads", "export"):
        raise HTTPException(status_code=403, detail="Missing permission: leads:export")
    conds = [lead_filter(scope)]
    if start or end:
        d_start, d_end = _period(start, end)
        s_utc, e_utc = crm_metrics.period_bounds(d_start, d_end)
        conds += [crm_metrics.lead_date_col() >= s_utc, crm_metrics.lead_date_col() < e_utc]
    if sheet:
        conds.append(TeleCallLead.sheet_tl_name == sheet)
    if status:
        conds.append(func.coalesce(TeleCallLead.status, "") == ("" if status == NO_STATUS else status))
    if owner.isdigit():
        conds.append(TeleCallLead.owner_user_id == int(owner))
    leads = (await db.execute(select(TeleCallLead).where(and_(*conds))
                              .order_by(crm_metrics.lead_date_col().desc()))).scalars().all()
    names = await user_names(db, {l.owner_user_id for l in leads})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "City", "Full name", "Phone", "Email", "Source", "Submitted (IST)", "Owner",
                "Person Calling (sheet)", "Status", "Stage", "Priority", "Next follow-up (IST)",
                "Last contact (IST)", "Phone model", "Service", "Coverage", "Potential value",
                "Sale amount", "Appointment date", "Remarks"])
    fmt = lambda d: to_ist(d).strftime("%Y-%m-%d %H:%M") if d else ""  # noqa: E731
    for l in leads:
        w.writerow([l.id, l.sheet_tl_name, l.full_name, l.phone, l.email, l.lead_source,
                    fmt(l.submitted_at or l.created_at), names.get(l.owner_user_id, ""), l.person_calling,
                    l.status or NO_STATUS, STAGE_LABELS.get(l.stage or "new", l.stage), l.priority or "",
                    fmt(l.next_follow_up_at), fmt(l.last_contact_at), l.phone_model or "", l.service_type or "",
                    l.coverage or "", l.potential_value or "", l.sale_amount or "", l.appointment_date or "",
                    (l.remarks or "").replace("\n", " ")])
    record_audit(db, user.id, "export", "tele_call_leads", None,
                 after={"rows": len(leads), "start": start, "end": end, "sheet": sheet, "status": status})
    await db.commit()
    filename = f"telecalling-leads-{ist_today().isoformat()}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── automation & targets settings ──────────────────────────────────
@router.get("/settings/automation")
async def get_automation_settings(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await _scope(db, user)
    return {"automation": await get_automation(db), "targets": await get_targets(db),
            "can_edit": scope.can_edit_settings, "go_live": iso_utc(await get_go_live(db))}


class AutomationUpdate(BaseModel):
    automation: Optional[dict] = None
    targets: Optional[dict] = None


def _validate_automation(a: dict) -> None:
    ints = ["first_call_minutes", "reassign_minutes", "escalate_minutes", "no_answer_retry_minutes",
            "busy_retry_minutes", "max_calls_per_day", "overdue_tl_minutes", "overdue_admin_minutes"]
    for k in ints:
        v = a.get(k)
        if not isinstance(v, int) or v < 1 or v > 10080:
            raise HTTPException(status_code=400, detail=f"{k} must be a whole number between 1 and 10080")
    if not (a["first_call_minutes"] <= a["reassign_minutes"] <= a["escalate_minutes"]):
        raise HTTPException(status_code=400, detail="First call ≤ reassign ≤ escalate minutes")
    wh = a.get("working_hours") or {}
    if not isinstance(wh.get("days"), list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in wh["days"]):
        raise HTTPException(status_code=400, detail="working_hours.days must be weekday numbers 0 (Mon)–6 (Sun)")
    for key in ("start", "end"):
        try:
            hh, mm = str(wh.get(key)).split(":")
            assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
        except Exception:
            raise HTTPException(status_code=400, detail=f"working_hours.{key} must be HH:MM")
    if str(wh["start"]) >= str(wh["end"]):
        raise HTTPException(status_code=400, detail="Working hours must start before they end")


@router.put("/settings/automation")
async def update_automation_settings(body: AutomationUpdate, db: AsyncSession = Depends(get_db),
                                     user=Depends(get_current_user)):
    scope = await _scope(db, user)
    if not scope.can_edit_settings:
        raise HTTPException(status_code=403, detail="Only Admin can change automation rules")
    before = {"automation": await get_automation(db), "targets": await get_targets(db)}
    out = {}
    if body.automation is not None:
        merged = {**before["automation"], **body.automation}
        _validate_automation(merged)
        out["automation"] = await save_automation(db, merged, user.id)
    if body.targets is not None:
        t = {**before["targets"], **body.targets}
        for k in ("first_call_pct", "followup_on_time_pct"):
            if not isinstance(t.get(k), (int, float)) or not 0 <= t[k] <= 100:
                raise HTTPException(status_code=400, detail=f"{k} must be 0–100")
        for k in ("followup_grace_minutes", "low_sample_leads"):
            if not isinstance(t.get(k), int) or t[k] < 0:
                raise HTTPException(status_code=400, detail=f"{k} must be a whole number ≥ 0")
        out["targets"] = await save_targets(db, t, user.id)
    record_audit(db, user.id, "settings_update", "crm_automation", None, before=before, after=out)
    await db.commit()
    return {"ok": True, **out}


@router.get("/automation/log")
async def automation_log(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user)):
    """Recent automatic actions (assignment, reassignment, escalation)."""
    scope = await _scope(db, user)
    rows = (await db.execute(
        select(TeleLeadActivity, TeleCallLead)
        .join(TeleCallLead, TeleCallLead.id == TeleLeadActivity.lead_id)
        .where(lead_filter(scope), TeleLeadActivity.user_id.is_(None),
               TeleLeadActivity.type.in_(["assignment", "system"]))
        .order_by(TeleLeadActivity.created_at.desc()).limit(limit)
    )).all()
    now = utcnow()
    open_fc = int((await db.execute(
        select(func.count(TeleLeadFollowup.id)).join(TeleCallLead, TeleCallLead.id == TeleLeadFollowup.lead_id)
        .where(lead_filter(scope), TeleLeadFollowup.status == "open", TeleLeadFollowup.kind == "first_call")
    )).scalar() or 0)
    urgent = int((await db.execute(
        select(func.count(TeleCallLead.id)).where(lead_filter(scope), TeleCallLead.is_urgent == True)  # noqa: E712
    )).scalar() or 0)
    return {
        "stats": {"open_first_calls": open_fc, "urgent": urgent},
        "items": [{
            "at": iso_utc(a.created_at), "lead_id": l.id, "lead_name": l.full_name, "city": l.sheet_tl_name,
            "type": a.type, "from": a.old_value, "to": a.new_value, "notes": a.notes,
            "source": (a.meta or {}).get("source"),
        } for a, l in rows],
        "now": iso_utc(now),
    }


# ── name aliases (sheet "Person Calling" → user) ───────────────────
@router.get("/settings/aliases")
async def list_aliases(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    await _scope(db, user)
    aliases = await get_aliases(db)
    names = await user_names(db, set(aliases.values()))
    return {"aliases": [{"alias": k, "user_id": v, "user_name": names.get(v)} for k, v in sorted(aliases.items())]}


class AliasRequest(BaseModel):
    alias: str
    user_id: Optional[int] = None  # None removes the alias


@router.put("/settings/aliases")
async def set_alias(body: AliasRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await _scope(db, user)
    if not scope.can_edit_settings:
        raise HTTPException(status_code=403, detail="Only Admin can map sheet names to users")
    aliases = await get_aliases(db)
    key = norm_name(body.alias)
    if not key:
        raise HTTPException(status_code=400, detail="alias is empty")
    if body.user_id is None:
        aliases.pop(key, None)
    else:
        if not (await db.execute(select(User.id).where(User.id == body.user_id))).scalar():
            raise HTTPException(status_code=404, detail="User not found")
        aliases[key] = body.user_id
    await save_aliases(db, aliases, user.id)
    record_audit(db, user.id, "alias_update", "crm_aliases", body.user_id, after={"alias": key, "user_id": body.user_id})
    await db.commit()
    return {"ok": True, "note": "Applied to unowned leads on the next sheet sync (within a minute)."}


# ── price book ─────────────────────────────────────────────────────
async def _can_edit_prices(db: AsyncSession, user: User, scope: CrmScope) -> bool:
    return scope.can_edit_settings or await _has_perm(db, user, "settings", "edit")


@router.get("/price-book")
async def get_price_book(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await _scope(db, user)
    rows = (await db.execute(select(PriceBookEntry).where(PriceBookEntry.is_active == True)  # noqa: E712
                             .order_by(PriceBookEntry.service_type, PriceBookEntry.phone_model))).scalars().all()
    grouped: dict[tuple, dict] = {}
    coverages: list[str] = ["Standard", "AppleCare+", "Samsung Care+", "Third-party insurance"]
    for r in rows:
        key = (r.phone_model, r.service_type)
        g = grouped.setdefault(key, {"phone_model": r.phone_model, "service_type": r.service_type, "prices": {},
                                     "updated_at": None})
        g["prices"][r.coverage] = float(r.price) if r.price is not None else None
        if r.coverage not in coverages:
            coverages.append(r.coverage)
        ts = iso_utc(r.updated_at)
        if ts and (g["updated_at"] is None or ts > g["updated_at"]):
            g["updated_at"] = ts
    return {"rows": list(grouped.values()), "coverages": coverages,
            "can_edit": await _can_edit_prices(db, user, scope)}


class PriceRowRequest(BaseModel):
    phone_model: str
    service_type: str
    prices: dict[str, Optional[float | str]]  # coverage -> price (None/"" = needs review)
    original_phone_model: Optional[str] = None
    original_service_type: Optional[str] = None


def _to_price(v) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        d = Decimal(str(v).replace(",", "").replace("₹", "").strip())
    except InvalidOperation:
        raise HTTPException(status_code=400, detail=f"Invalid price: {v}")
    if d < 0:
        raise HTTPException(status_code=400, detail="Prices cannot be negative")
    return d


@router.put("/price-book")
async def upsert_price_row(body: PriceRowRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Create or edit one model + service row (all coverages at once).
    Open leads pick up new prices when their device details are next saved;
    converted sale values never change."""
    scope = await _scope(db, user)
    if not await _can_edit_prices(db, user, scope):
        raise HTTPException(status_code=403, detail="Only Admin can edit the price book")
    model, service = body.phone_model.strip(), body.service_type.strip()
    if not model or not service:
        raise HTTPException(status_code=400, detail="Phone model and service are required")
    orig_model = (body.original_phone_model or model).strip()
    orig_service = (body.original_service_type or service).strip()
    existing = (await db.execute(select(PriceBookEntry).where(
        func.lower(PriceBookEntry.phone_model) == orig_model.lower(),
        func.lower(PriceBookEntry.service_type) == orig_service.lower(),
    ))).scalars().all()
    by_cov = {e.coverage.lower(): e for e in existing}
    before = {e.coverage: (float(e.price) if e.price is not None else None) for e in existing}
    for cov, raw in body.prices.items():
        price = _to_price(raw)
        e = by_cov.pop(cov.strip().lower(), None)
        if e:
            e.phone_model, e.service_type, e.price, e.is_active, e.updated_by = model, service, price, True, user.id
        else:
            db.add(PriceBookEntry(phone_model=model, service_type=service, coverage=cov.strip(), price=price,
                                  is_active=True, updated_by=user.id))
    for e in by_cov.values():  # renamed row: carry over coverages not in the request
        e.phone_model, e.service_type = model, service
    record_audit(db, user.id, "price_update", "price_book", None,
                 before={"row": f"{orig_model} · {orig_service}", "prices": before},
                 after={"row": f"{model} · {service}", "prices": {k: str(v) for k, v in body.prices.items()}})
    await db.commit()
    return {"ok": True}


@router.delete("/price-book")
async def delete_price_row(phone_model: str = Query(...), service_type: str = Query(...),
                           db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await _scope(db, user)
    if not await _can_edit_prices(db, user, scope):
        raise HTTPException(status_code=403, detail="Only Admin can edit the price book")
    rows = (await db.execute(select(PriceBookEntry).where(
        func.lower(PriceBookEntry.phone_model) == phone_model.strip().lower(),
        func.lower(PriceBookEntry.service_type) == service_type.strip().lower(),
    ))).scalars().all()
    for r in rows:
        r.is_active = False
    record_audit(db, user.id, "price_remove", "price_book", None, after={"row": f"{phone_model} · {service_type}"})
    await db.commit()
    return {"ok": True, "removed": len(rows)}


# ── data quality ───────────────────────────────────────────────────
@router.get("/data-quality")
async def data_quality(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await _scope(db, user)
    base = lead_filter(scope)
    now = utcnow()
    open_stage = func.coalesce(TeleCallLead.stage, "new").notin_(list(CLOSED_STAGES))

    async def sample(*conds, limit=20):
        rows = (await db.execute(select(TeleCallLead).where(base, *conds)
                                 .order_by(crm_metrics.lead_date_col().desc()).limit(limit))).scalars().all()
        total = int((await db.execute(select(func.count(TeleCallLead.id)).where(base, *conds))).scalar() or 0)
        return {"count": total, "items": [{"id": l.id, "full_name": l.full_name, "phone": l.phone,
                                           "city": l.sheet_tl_name, "created_time": l.created_time,
                                           "status": l.status or NO_STATUS} for l in rows]}

    unknown = (await db.execute(
        select(TeleCallLead.status, func.count(TeleCallLead.id))
        .where(base, func.coalesce(TeleCallLead.status, "") != "", TeleCallLead.status.notin_(STATUSES))
        .group_by(TeleCallLead.status).order_by(func.count(TeleCallLead.id).desc())
    )).all()
    unmatched = (await db.execute(
        select(TeleCallLead.person_calling, TeleCallLead.sheet_tl_name, func.count(TeleCallLead.id))
        .where(base, func.coalesce(TeleCallLead.person_calling, "") != "", TeleCallLead.owner_user_id.is_(None))
        .group_by(TeleCallLead.person_calling, TeleCallLead.sheet_tl_name)
        .order_by(func.count(TeleCallLead.id).desc())
    )).all()

    # duplicates: same city + same phone (last 10 digits)
    phones = (await db.execute(select(TeleCallLead.id, TeleCallLead.sheet_tl_name, TeleCallLead.phone,
                                      TeleCallLead.full_name).where(base))).all()
    groups: dict[tuple, list] = defaultdict(list)
    for lid, city, phone, name in phones:
        ph = norm_phone(phone)
        if len(ph) >= 8:
            groups[(city, ph)].append({"id": lid, "full_name": name, "phone": phone})
    dups = [{"city": k[0], "phone": k[1], "leads": v} for k, v in groups.items() if len(v) > 1]
    dups.sort(key=lambda d: -len(d["leads"]))

    return {
        "missing_phone": await sample(func.coalesce(TeleCallLead.phone, "") == ""),
        "unparseable_created_time": await sample(func.coalesce(TeleCallLead.created_time, "") != "",
                                                 TeleCallLead.submitted_at.is_(None)),
        "no_status_24h": await sample(func.coalesce(TeleCallLead.status, "") == "",
                                      crm_metrics.lead_date_col() < now - timedelta(hours=24)),
        "unassigned_open": await sample(TeleCallLead.owner_user_id.is_(None), open_stage),
        "missing_model": await sample(TeleCallLead.phone_model.is_(None), open_stage),
        "unknown_statuses": [{"status": s, "count": int(c)} for s, c in unknown],
        "unmatched_names": [{"name": n, "city": c, "count": int(k)} for n, c, k in unmatched[:50]],
        "duplicates": {"count": len(dups), "items": dups[:30]},
        "can_fix_aliases": scope.can_edit_settings,
    }


# ── audit history ──────────────────────────────────────────────────
@router.get("/audit")
async def audit_history(resource: str = Query(""), limit: int = Query(100, ge=1, le=500),
                        db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await _scope(db, user)
    if not scope.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if resource:
        q = q.where(AuditLog.resource == resource)
    rows = (await db.execute(q)).scalars().all()
    names = await user_names(db, {r.user_id for r in rows})
    return {"items": [{
        "id": r.id, "at": iso_utc(r.created_at), "user": names.get(r.user_id, "System"),
        "action": r.action, "resource": r.resource, "resource_id": r.resource_id,
        "before": r.before_json, "after": r.after_json,
    } for r in rows]}


# ── integrations (sheet sync health) ───────────────────────────────
@router.get("/integrations")
async def integrations(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await _scope(db, user)
    stats = {r[0]: (int(r[1]), r[2]) for r in (await db.execute(
        select(TeleCallLead.sheet_tl_name, func.count(TeleCallLead.id), func.max(TeleCallLead.last_synced_at))
        .group_by(TeleCallLead.sheet_tl_name)
    )).all()}
    app_only = dict((await db.execute(
        select(TeleCallLead.sheet_tl_name, func.count(TeleCallLead.id))
        .where(func.coalesce(TeleCallLead.spreadsheet_id, "") == "").group_by(TeleCallLead.sheet_tl_name)
    )).all())
    members = await sheet_members(db, None)
    per_sheet = defaultdict(list)
    for m in members:
        for sh in m["sheets"]:
            per_sheet[sh].append({"id": m["id"], "name": m["name"], "role": m["role"], "available": m["available"]})
    sheets = []
    for cfg in TELE_CALL_SHEETS:
        name = cfg["tl_name"]
        if not scope.is_admin and name not in scope.sheets:
            continue
        count, last = stats.get(name, (0, None))
        run = LAST_SYNC.get(name)
        sheets.append({
            "city": name,
            "spreadsheet_id": cfg["spreadsheet_id"] if scope.is_admin else None,
            "leads": count, "app_only_leads": int(app_only.get(name, 0)),
            "last_synced_at": iso_utc(last.replace(tzinfo=None) if last and last.tzinfo else last),
            "last_run": run, "people": per_sheet.get(name, []),
        })
    automation = await get_automation(db)
    return {
        "sheets": sheets, "direction": "Google Sheet → app (read-only; the app never writes to the sheets)",
        "sync_interval_minutes": 1, "automation_enabled": automation.get("enabled", True),
        "go_live": iso_utc(await get_go_live(db)),
    }
