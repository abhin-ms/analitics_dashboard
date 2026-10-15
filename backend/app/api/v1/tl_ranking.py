"""Team leader ranking for the team leader and admin dashboards.

GET /tl-ranking?start=&end=  — every team leader's score, rank and area
scores for the period (scoring rules: services/tl_ranking.py).
  * admin tier: every team leader with full details
  * Team Leader: everyone's rank and score, but only their own details
  * anyone else: 403
"""
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import ADMIN_TIER_ROLES, get_current_user, get_db
from ...models.models import (
    McpDailySale, Role, Store, StoreMcpAlias, StoreWalkin, TeleCallLead, TeleLeadFollowup, TeleSheetAssignment, User,
)
from ...services import sales_report_service
from ...services import tl_ranking as scoring
from ...services.crm.config import get_targets
from ...services.crm.metrics import lead_date_col, period_bounds
from ...services.crm.status import NOT_CONNECTED_STATUSES
from ...services.crm.timeutil import utcnow
from ...services.store_portfolio import prorated_target, shop_of, shop_of_sheet
from .store_portfolio import COUNTRY_CURRENCY, MAX_RANGE_DAYS, _lead_targets, _store_lead_target

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tl-ranking", tags=["tl-ranking"])

# Accounts the sheet syncs create that are not real team leaders.
PLACEHOLDER_NAMES = {"unassigned", "tl name"}
CALLED_AFTER_HOURS = 24


def _phone_key(lead: TeleCallLead) -> str:
    digits = re.sub(r"\D", "", lead.phone or "")
    return digits[-10:] if len(digits) >= 10 else f"id{lead.id}"


def _currency(store: Store) -> str:
    # currency_code defaults to INR even for stores abroad, so the country decides there
    if store.country and store.country != "India" and store.country in COUNTRY_CURRENCY:
        return COUNTRY_CURRENCY[store.country]
    return store.currency_code or "INR"


async def _team_leaders(db: AsyncSession) -> list[dict]:
    """Team leaders who run at least one active store or lead sheet tab."""
    users = (await db.execute(
        select(User).join(Role, Role.id == User.role_id).where(Role.name == "Team Leader")
    )).scalars().all()
    stores = (await db.execute(select(Store).where(Store.is_active == True))).scalars().all()  # noqa: E712
    sheets: dict[int, list[str]] = defaultdict(list)
    for uid, sheet in (await db.execute(select(TeleSheetAssignment.user_id, TeleSheetAssignment.sheet_tl_name))).all():
        sheets[uid].append(sheet)
    out = []
    for u in users:
        if " ".join((u.name or "").lower().split()) in PLACEHOLDER_NAMES:
            continue
        own = [s for s in stores if s.team_leader_id == u.id]
        if own or sheets.get(u.id):
            out.append({"user": u, "stores": sorted(own, key=lambda s: s.name), "sheets": sorted(sheets.get(u.id, []))})
    return out


async def _measure(db: AsyncSession, tl: dict, start: date, end: date, *, now: datetime,
                   lead_targets: dict, grace: timedelta, aliased: set[int]) -> tuple[dict, dict]:
    """Area scores and the figures behind them for one team leader over
    [start, end] (end already capped at today)."""
    stores, sheets = tl["stores"], tl["sheets"]
    store_ids = [s.id for s in stores]

    # ── Sales: each store against its own target ──
    revenue = dict((await db.execute(
        select(McpDailySale.store_id, func.coalesce(func.sum(McpDailySale.revenue), 0))
        .where(McpDailySale.store_id.in_(store_ids or [-1]), McpDailySale.date >= start, McpDailySale.date <= end)
        .group_by(McpDailySale.store_id)
    )).all())
    store_rows = []
    for s in stores:
        # Same rule as the sales report: MCP's target is trusted only for stores MCP maintains.
        monthly = float(s.monthly_target or 0) if s.id in aliased else 0.0
        target = prorated_target(monthly, start, end)
        rev = float(revenue.get(s.id) or 0)
        store_rows.append({"name": s.name, "currency": _currency(s),
                           "revenue": round(rev, 2), "target": round(target, 2),
                           "pct": round(rev / target * 100, 1) if target > 0 else None})
    with_target = [r for r in store_rows if r["target"] > 0]

    # ── Leads on the team leader's sheet tabs and stores ──
    clauses = []
    if sheets:
        clauses.append(TeleCallLead.sheet_tl_name.in_(sheets))
    if store_ids:
        clauses.append(TeleCallLead.store_id.in_(store_ids))
    scope = or_(*clauses) if clauses else false()
    s_utc, e_utc = period_bounds(start, end)
    leads = (await db.execute(
        select(TeleCallLead).where(scope, lead_date_col() >= s_utc, lead_date_col() < e_utc)
    )).scalars().all()
    groups: dict[str, list[TeleCallLead]] = defaultdict(list)
    for l in leads:
        groups[_phone_key(l)].append(l)
    unique = len(groups)
    converted = sum(1 for g in groups.values()
                    if any(l.status == "Sale Conversion" or l.stage == "converted" for l in g))

    # One lead target per sheet tab: the matching store's own target, else the default.
    by_shop = {shop_of(s.name): s for s in stores if shop_of(s.name)}
    tab_targets = []
    for tab in sheets:
        store = by_shop.get(shop_of_sheet(tab))
        tab_targets.append(_store_lead_target(lead_targets, store.id) if store else lead_targets["default"])
    if not tab_targets:  # no sheet tabs: the stores' own targets
        tab_targets = [_store_lead_target(lead_targets, s.id) for s in stores]
    lead_monthly = sum(float(t["leads_monthly"] or 0) for t in tab_targets)
    lead_target = prorated_target(lead_monthly, start, end)
    conv_targets = [float(t["conversion_pct"]) for t in tab_targets if t.get("conversion_pct")]
    conv_target = sum(conv_targets) / len(conv_targets) if conv_targets else 0.0

    # ── Telecalling ──
    due_cutoff = now - timedelta(hours=CALLED_AFTER_HOURS)
    due = [l for l in leads if (l.submitted_at or l.created_at) and (l.submitted_at or l.created_at) <= due_cutoff]
    called = sum(1 for l in due if l.status or l.first_contact_at)
    attempted = [l for l in leads if l.status]
    connected = sum(1 for l in attempted if l.status not in NOT_CONNECTED_STATUSES)
    fu_due = fu_on_time = 0
    for fu in (await db.execute(
        select(TeleLeadFollowup).join(TeleCallLead, TeleCallLead.id == TeleLeadFollowup.lead_id)
        .where(scope, TeleLeadFollowup.due_at >= s_utc, TeleLeadFollowup.due_at < e_utc)
    )).scalars().all():
        # the same rules as the telecaller reports (crm.metrics.sla_metrics)
        if fu.status == "cancelled" or (fu.status == "open" and fu.due_at > now):
            continue
        if fu.status in ("reassigned", "rescheduled") and fu.completed_at and fu.completed_at <= fu.due_at:
            continue
        fu_due += 1
        allowed = fu.due_at if fu.kind == "first_call" else fu.due_at + grace
        if fu.status == "done" and fu.completed_at is not None and fu.completed_at <= allowed:
            fu_on_time += 1

    # ── Walk-ins that bought: bills only on days the walk-ins sheet covers ──
    walk = (await db.execute(select(StoreWalkin).where(
        StoreWalkin.store_id.in_(store_ids or [-1]), StoreWalkin.date >= start, StoreWalkin.date <= end,
    ))).scalars().all()
    walkins = sum((w.actual if w.actual is not None else w.dsr) or 0 for w in walk)
    walk_days = {(w.store_id, w.date) for w in walk}
    walk_bills = 0
    if walk_days:
        for sid, d, n in (await db.execute(
            select(McpDailySale.store_id, McpDailySale.date, McpDailySale.new_sale_count).where(
                McpDailySale.store_id.in_({sid for sid, _d in walk_days}),
                McpDailySale.date.in_({d for _s, d in walk_days}))
        )).all():
            if (sid, d) in walk_days:
                walk_bills += n or 0

    called_pct = scoring.pct(called, len(due))
    connected_pct = scoring.pct(connected, len(attempted))
    fu_pct = scoring.pct(fu_on_time, fu_due)
    lead_conv = scoring.pct(converted, unique)
    walk_pct = scoring.pct(walk_bills, walkins)
    areas = {
        "sales": scoring.sales_score(with_target),
        "tele": scoring.tele_score(called_pct, connected_pct, fu_pct),
        "leads": scoring.leads_score(unique, lead_target),
        "conv": scoring.conv_score(lead_conv, conv_target, walk_pct),
    }
    r1 = lambda v: round(v, 1) if v is not None else None  # noqa: E731
    details = {
        "sales": {"stores": store_rows, "with_target": len(with_target),
                  "on_target": sum(1 for r in with_target if r["revenue"] >= r["target"])},
        "tele": {"leads_due": len(due), "called": called, "called_pct": r1(called_pct),
                 "attempted": len(attempted), "connected": connected, "connected_pct": r1(connected_pct),
                 "followups_due": fu_due, "followups_on_time": fu_on_time, "followups_pct": r1(fu_pct)},
        "leads": {"leads": unique, "entries": len(leads), "target": round(lead_target),
                  "short_by": max(0, round(lead_target) - unique), "sheet_tabs": sheets},
        "conv": {"converted": converted, "lead_conv_pct": r1(lead_conv), "conv_target_pct": r1(conv_target),
                 "walkins": walkins, "walkin_bills": walk_bills, "walkin_buy_pct": r1(walk_pct),
                 "walkin_target_pct": scoring.WALKIN_BUY_TARGET_PCT},
    }
    return areas, details


async def _ensure_sales(db: AsyncSession, start: date, end: date) -> None:
    try:
        await sales_report_service._ensure_mcp_coverage(db, start, end)
    except Exception as e:  # stale sales are better than no ranking
        logger.warning("tl-ranking: MCP coverage %s..%s failed: %s", start, end, e)
        await db.rollback()


@router.get("")
async def team_leader_ranking(
    start: Optional[date] = None,
    end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none() or ""
    is_admin = role in ADMIN_TIER_ROLES
    if not is_admin and role != "Team Leader":
        raise HTTPException(status_code=403, detail="Only team leaders and admins see the team leader ranking")

    today = date.today()
    end = end or today
    start = start or end.replace(day=1)
    if start > end:
        raise HTTPException(status_code=400, detail="start must be on or before end")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Pick a period of at most {MAX_RANGE_DAYS} days")
    # Figures and targets count only the days so far.
    counted_end = min(end, today)
    prev_start, prev_end, prev_label = scoring.previous_window(start, max(counted_end, start))

    tls = await _team_leaders(db)
    lead_targets = await _lead_targets(db)
    grace = timedelta(minutes=(await get_targets(db)).get("followup_grace_minutes", 15))
    aliased = set((await db.execute(select(StoreMcpAlias.store_id).distinct())).scalars().all())
    now = utcnow()

    entries = []
    if start <= counted_end:
        await _ensure_sales(db, start, counted_end)
    await _ensure_sales(db, prev_start, prev_end)
    for tl in tls:
        u = tl["user"]
        if start <= counted_end:
            areas, details = await _measure(db, tl, start, counted_end, now=now, lead_targets=lead_targets,
                                            grace=grace, aliased=aliased)
        else:  # a period entirely in the future: nothing to score yet
            areas, details = {k: None for k, _l, _w in scoring.AREAS}, {}
        prev_areas, _ = await _measure(db, tl, prev_start, prev_end, now=now, lead_targets=lead_targets,
                                       grace=grace, aliased=aliased)
        entries.append(scoring.Entry(team_leader_id=u.id, name=u.name, areas=areas, details=details,
                                     stores=[s.name for s in tl["stores"]], previous_score=scoring.overall(prev_areas)))

    rows = scoring.rank(entries)
    average = scoring.team_average(rows)
    if not is_admin:  # a team leader sees where others stand, not their breakdown
        for r in rows:
            if r["team_leader_id"] != user.id:
                r.update(areas=None, weakest=None, details=None)

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "counted_to": counted_end.isoformat(),
                   "previous": {"start": prev_start.isoformat(), "end": prev_end.isoformat(), "label": prev_label}},
        "viewer": {"is_admin": is_admin, "team_leader_id": None if is_admin else user.id},
        "areas": [{"key": k, "label": label, "weight": w} for k, label, w in scoring.AREAS],
        "team_average": average,
        "rows": rows,
    }
