"""One metrics service for the Telecaller, Team Leader and Admin views.

Two families of numbers:
  * status-based (works on all historic sheet data immediately): lead
    counts by status, conversions, connected/not-connected, sale amount;
  * SLA-based (from go-live, needs the CRM timeline): first call within N
    minutes, follow-ups on time, calls logged, average time to first call.
Missed deadlines are counted against the follow-up's owner AT THAT TIME.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import TeleCallLead, TeleLeadActivity, TeleLeadFollowup
from .engine import parse_amount
from .status import (
    ACTIVE_STATUSES, NO_STATUS, NOT_CONNECTED_STATUSES, OUTCOMES, STATUSES,
)
from .timeutil import from_ist, working_minutes_between

CONNECTED_OUTCOMES = {k for k, v in OUTCOMES.items() if v.get("connected")}


def lead_date_col():
    """When a lead arrived: Meta submission time if parsed, else CRM receipt."""
    return func.coalesce(TeleCallLead.submitted_at, TeleCallLead.created_at)


def period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """IST calendar dates [start, end] -> naive UTC [start, end+1day)."""
    s = from_ist(datetime.combine(start, datetime.min.time()))
    e = from_ist(datetime.combine(end + timedelta(days=1), datetime.min.time()))
    return s, e


def previous_period(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def status_counts(leads) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for l in leads:
        counts[l.status or NO_STATUS] += 1
    ordered = {s: counts[s] for s in [NO_STATUS] + STATUSES if counts.get(s)}
    for s, c in counts.items():  # unknown statuses kept, never dropped
        if s not in ordered:
            ordered[s] = c
    return ordered


def lead_kpis(leads) -> dict:
    total = len(leads)
    by = defaultdict(int)
    sale = 0.0
    for l in leads:
        by[l.status or ""] += 1
        if l.status == "Sale Conversion":
            sale += parse_amount(l.sale_amount)
    not_connected = sum(by[s] for s in NOT_CONNECTED_STATUSES)
    no_status = by[""]
    attempted = total - no_status
    connected = attempted - not_connected
    converted = by["Sale Conversion"]
    return {
        "total_leads": total,
        "converted": converted,
        "appointments": by["Appointment"],
        "will_visit": by["Will Visit"],
        "call_back_later": by["Call back later"],
        "not_interested": by["Not Interested"],
        "no_status": no_status,
        "active": sum(by[s] for s in ACTIVE_STATUSES),
        "calls_connected": connected,
        "calls_not_connected": not_connected,
        "connected_pct": round(connected / attempted * 100, 1) if attempted else 0.0,
        "conversion_pct": round(converted / total * 100, 1) if total else 0.0,
        "total_sale_amount": sale,
    }


def pct_change(cur: float, prev: float) -> float | None:
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


async def leads_in_period(db: AsyncSession, scope_clause, start_utc: datetime | None,
                          end_utc: datetime | None, extra=None) -> list[TeleCallLead]:
    q = select(TeleCallLead).where(scope_clause)
    if start_utc is not None:
        q = q.where(lead_date_col() >= start_utc)
    if end_utc is not None:
        q = q.where(lead_date_col() < end_utc)
    if extra is not None:
        q = q.where(extra)
    return list((await db.execute(q)).scalars().all())


async def sla_metrics(db: AsyncSession, agent_ids: list[int], start_utc: datetime, end_utc: datetime,
                      *, now: datetime, automation: dict, targets: dict) -> dict[int, dict]:
    """First-call, follow-up and call-log metrics per agent for a period."""
    wh = automation["working_hours"]
    grace = timedelta(minutes=targets.get("followup_grace_minutes", 15))
    out: dict[int, dict] = {a: {
        "first_calls_total": 0, "first_calls_on_time": 0, "first_call_minutes": [],
        "followups_total": 0, "followups_on_time": 0,
        "calls_logged": 0, "calls_connected_logged": 0,
    } for a in agent_ids}
    if not agent_ids:
        return {}

    fus = (await db.execute(
        select(TeleLeadFollowup).where(
            TeleLeadFollowup.owner_user_id.in_(agent_ids),
            TeleLeadFollowup.due_at >= start_utc, TeleLeadFollowup.due_at < end_utc,
        )
    )).scalars().all()
    for fu in fus:
        m = out.get(fu.owner_user_id)
        if m is None or fu.status == "cancelled":
            continue
        if fu.status == "open" and fu.due_at > now:
            continue  # not due yet — neither on time nor missed
        if (fu.status in ("reassigned", "rescheduled") and fu.completed_at
                and fu.completed_at <= fu.due_at):
            continue  # handed over / moved before it was due — not a miss
        done_on_time = fu.status == "done" and fu.completed_at is not None
        if fu.kind == "first_call":
            m["first_calls_total"] += 1
            if done_on_time and fu.completed_at <= fu.due_at:
                m["first_calls_on_time"] += 1
            if fu.status == "done" and fu.completed_at and fu.created_at:
                m["first_call_minutes"].append(working_minutes_between(fu.created_at, fu.completed_at, wh))
        else:
            m["followups_total"] += 1
            if done_on_time and fu.completed_at <= fu.due_at + grace:
                m["followups_on_time"] += 1

    calls = (await db.execute(
        select(TeleLeadActivity.user_id, TeleLeadActivity.outcome, func.count(TeleLeadActivity.id))
        .where(TeleLeadActivity.user_id.in_(agent_ids), TeleLeadActivity.type == "call",
               TeleLeadActivity.created_at >= start_utc, TeleLeadActivity.created_at < end_utc)
        .group_by(TeleLeadActivity.user_id, TeleLeadActivity.outcome)
    )).all()
    for uid, outcome, cnt in calls:
        m = out.get(uid)
        if m is None:
            continue
        m["calls_logged"] += int(cnt)
        if outcome in CONNECTED_OUTCOMES:
            m["calls_connected_logged"] += int(cnt)

    for m in out.values():
        mins = m.pop("first_call_minutes")
        m["avg_first_call_minutes"] = round(sum(mins) / len(mins), 1) if mins else None
        m["first_call_pct"] = (round(m["first_calls_on_time"] / m["first_calls_total"] * 100, 1)
                               if m["first_calls_total"] else None)
        m["followups_on_time_pct"] = (round(m["followups_on_time"] / m["followups_total"] * 100, 1)
                                      if m["followups_total"] else None)
        m["connected_logged_pct"] = (round(m["calls_connected_logged"] / m["calls_logged"] * 100, 1)
                                     if m["calls_logged"] else None)
    return out


async def agent_report(db: AsyncSession, agents: list[dict], start: date, end: date, *,
                       now: datetime, automation: dict, targets: dict,
                       sheet: str | None = None) -> list[dict]:
    """Per-agent rows for Reports / dashboards: this period vs the previous
    period of the same length, with target flags and a low-sample flag."""
    ids = [a["id"] for a in agents]
    if not ids:
        return []
    cur_s, cur_e = period_bounds(start, end)
    ps, pe = previous_period(start, end)
    prev_s, prev_e = period_bounds(ps, pe)

    extra = TeleCallLead.sheet_tl_name == sheet if sheet else None
    base = TeleCallLead.owner_user_id.in_(ids)
    cur_leads = await leads_in_period(db, base, cur_s, cur_e, extra)
    prev_leads = await leads_in_period(db, base, prev_s, prev_e, extra)
    by_agent_cur: dict[int, list] = defaultdict(list)
    by_agent_prev: dict[int, list] = defaultdict(list)
    for l in cur_leads:
        by_agent_cur[l.owner_user_id].append(l)
    for l in prev_leads:
        by_agent_prev[l.owner_user_id].append(l)

    sla_cur = await sla_metrics(db, ids, cur_s, cur_e, now=now, automation=automation, targets=targets)
    sla_prev = await sla_metrics(db, ids, prev_s, prev_e, now=now, automation=automation, targets=targets)

    low_sample = targets.get("low_sample_leads", 20)
    rows = []
    for a in agents:
        k = lead_kpis(by_agent_cur[a["id"]])
        kp = lead_kpis(by_agent_prev[a["id"]])
        s = sla_cur.get(a["id"], {})
        sp = sla_prev.get(a["id"], {})
        fc_pct, fu_pct = s.get("first_call_pct"), s.get("followups_on_time_pct")
        rows.append({
            "user_id": a["id"], "name": a["name"], "role": a.get("role"),
            "sheets": a.get("sheets", []), "available": a.get("available", True),
            **k,
            "status_counts": status_counts(by_agent_cur[a["id"]]),
            **s,
            "previous": {
                "total_leads": kp["total_leads"], "converted": kp["converted"],
                "conversion_pct": kp["conversion_pct"], "connected_pct": kp["connected_pct"],
                "first_call_pct": sp.get("first_call_pct"),
                "followups_on_time_pct": sp.get("followups_on_time_pct"),
                "calls_logged": sp.get("calls_logged", 0),
            },
            "low_sample": k["total_leads"] < low_sample,
            "below_target": {
                "first_call": fc_pct is not None and fc_pct < targets["first_call_pct"],
                "followups": fu_pct is not None and fu_pct < targets["followup_on_time_pct"],
            },
        })
    rows.sort(key=lambda r: (-r["total_leads"], r["name"].lower()))
    return rows


def daily_trend(leads, start: date, end: date) -> list[dict]:
    """Leads received and converted per IST day in [start, end]."""
    from .timeutil import to_ist
    days: dict[str, dict] = {}
    d = start
    while d <= end:
        days[d.isoformat()] = {"date": d.isoformat(), "leads": 0, "converted": 0, "contacted": 0}
        d += timedelta(days=1)
    for l in leads:
        when = l.submitted_at or l.created_at
        if not when:
            continue
        key = to_ist(when).date().isoformat()
        if key in days:
            days[key]["leads"] += 1
            if l.status == "Sale Conversion":
                days[key]["converted"] += 1
            if l.status:
                days[key]["contacted"] += 1
    return list(days.values())


async def queue_counts(db: AsyncSession, scope_clause, *, now: datetime,
                       owner_id: int | None = None) -> dict:
    """The four "today" tiles: first contact pending, due today (not yet
    overdue), overdue, and open leads with no owner."""
    from .status import CLOSED_STAGES
    from .timeutil import ist_day_bounds_utc, ist_today

    _, day_end = ist_day_bounds_utc(ist_today(now))
    q = (select(TeleLeadFollowup.kind, TeleLeadFollowup.due_at)
         .join(TeleCallLead, TeleCallLead.id == TeleLeadFollowup.lead_id)
         .where(scope_clause, TeleLeadFollowup.status == "open"))
    if owner_id is not None:
        q = q.where(TeleLeadFollowup.owner_user_id == owner_id)
    first_contact = due_today = overdue = 0
    for kind, due in (await db.execute(q)).all():
        if kind == "first_call":
            first_contact += 1
        if due < now:
            overdue += 1
        elif due < day_end:
            due_today += 1
    unassigned = int((await db.execute(
        select(func.count(TeleCallLead.id)).where(
            scope_clause, TeleCallLead.owner_user_id.is_(None),
            func.coalesce(TeleCallLead.stage, "new").notin_(list(CLOSED_STAGES)),
        )
    )).scalar() or 0)
    return {"first_contact_pending": first_contact, "due_today": due_today,
            "overdue": overdue, "unassigned": unassigned}
