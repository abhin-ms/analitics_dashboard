"""Per-section AI context builders for the Analytics tabs of each dashboard page.

Each builder returns a compact dict: {kpis, top?, bottom?, highlights_auto, concerns_auto}.
The same output schema (summary/highlights/concerns/recommendations/anomalies) is used
across all sections so the frontend renders uniformly.
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import (
    Store, User, DailySubmission, Lead, LostReason, Campaign, Task,
    Investment, KPIWeight, IncentiveBand,
)
from .sales_report_service import get_sales_report

logger = logging.getLogger(__name__)


def _month_range(month: str):
    start = date.fromisoformat(f"{month}-01")
    nxt = start.replace(day=28) + timedelta(days=4)
    end = nxt - timedelta(days=nxt.day)
    return start, end


def _num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct(num, den):
    return round(_num(num) / _num(den) * 100, 1) if _num(den) > 0 else 0.0


JSON_SCHEMA = """Respond ONLY with a single valid JSON object matching exactly this schema:
{
  "summary": "2-4 sentence executive summary",
  "highlights": ["3-6 short positive callouts, each <= 12 words"],
  "concerns": ["3-6 short risk callouts, each <= 12 words"],
  "recommendations": [
    {"priority": "critical|high|strategic", "title": "short title", "detail": "one or two sentences with names and numbers", "owner": "suggested owner or role"}
  ],
  "anomalies": [
    {"severity": "critical|warning|info", "store": "store or entity name", "metric": "metric name", "observation": "what is wrong", "suggested_action": "one short sentence"}
  ]
}"""

COMMON_RULES = """Rules:
- recommendations and anomalies: limit to 5 items each, ordered by importance.
- Use exact store, TL, campaign, or task names from the data.
- Put numbers (percentages, amounts) from the data into the text.
- Do NOT wrap the JSON in markdown code fences."""


def _make_prompt(role_and_data: str) -> str:
    return f"{role_and_data}\n\n{JSON_SCHEMA}\n\n{COMMON_RULES}"


# ── Section builders ──────────────────────────────────────────────────────
async def _sales_context(db: AsyncSession, month: str) -> dict:
    from .ai_summary_service import _ops_context

    ops = await _ops_context(db, month)
    kpis = ops["kpis"]
    top = [{"name": t["store"], "value": _num(t["mtd"]), "sub": f"{t['ach_pct']}%", "ach_pct": t["ach_pct"]} for t in ops["top_stores"]]
    bottom = [{"name": t["store"], "value": _num(t["mtd"]), "sub": f"{t['ach_pct']}%", "ach_pct": t["ach_pct"]} for t in ops["bottom_stores"]]
    change_pct = ops["prior_month_comparison"].get("revenue_change_pct")
    return {
        "kpis": kpis,
        "top": top,
        "bottom": bottom,
        "revenue_trend": ops["revenue_trend"],
        "tl_list": ops["tl_list"],
        "prior_month_comparison": ops["prior_month_comparison"],
        "detected_issues": ops["detected_issues"],
        "highlights_auto": [
            f"Top store: {top[0]['name']} at {top[0]['sub']}" if top else "No store data",
            f"{kpis['total_walkins']} walk-ins with {kpis['conv_pct']}% conversion" if kpis.get("total_walkins") else "No walk-in data",
            f"{kpis['units_sold']} units sold across {kpis['store_count']} stores" if kpis.get("units_sold") else None,
            f"Revenue up {change_pct}% vs last month" if change_pct is not None and change_pct > 0 else None,
        ],
        "concerns_auto": [
            f"{kpis['rag']['red']} stores below 35% target" if kpis["rag"].get("red") else None,
            f"Projected {kpis['pace_vs_target_pct']}% of target at current pace" if kpis.get("pace_vs_target_pct") is not None else None,
            f"Revenue down {abs(change_pct)}% vs last month" if change_pct is not None and change_pct < 0 else None,
            f"{len(ops['detected_issues'])} auto-detected issue(s) this month" if ops["detected_issues"] else None,
        ],
    }


async def _operations_context(db: AsyncSession, month: str) -> dict:
    start, end = _month_range(month)
    rows = (await db.execute(
        select(DailySubmission).where(DailySubmission.date >= start, DailySubmission.date <= end)
    )).scalars().all()
    stores = {s.id: s for s in (await db.execute(select(Store))).scalars().all()}
    active_ids = [sid for sid, s in stores.items() if s.is_active]
    days = (end - start).days + 1

    per = {}
    tot = {"revenue": 0.0, "units": 0, "walk_ins": 0, "conversions": 0, "calls": 0, "connected": 0,
           "care_plus": 0, "complaints_in": 0, "complaints_resolved": 0, "training_days": 0,
           "app_days": 0, "submissions": 0, "stock_var": 0, "stock_sold": 0}
    for r in rows:
        p = per.setdefault(r.store_id, {
            "name": stores.get(r.store_id).name if stores.get(r.store_id) else f"Store {r.store_id}",
            "revenue": 0.0, "units": 0, "walk_ins": 0, "conversions": 0,
        })
        p["revenue"] += _num(r.revenue)
        p["units"] += r.units_sold or 0
        p["walk_ins"] += r.walk_ins or 0
        p["conversions"] += r.walk_in_conversions or 0
        tot["revenue"] += _num(r.revenue)
        tot["units"] += r.units_sold or 0
        tot["walk_ins"] += r.walk_ins or 0
        tot["conversions"] += r.walk_in_conversions or 0
        tot["calls"] += r.calls_made or 0
        tot["connected"] += r.calls_connected or 0
        tot["care_plus"] += r.care_plus_attached or 0
        tot["complaints_in"] += r.complaints_in or 0
        tot["complaints_resolved"] += r.complaints_resolved or 0
        tot["training_days"] += 1 if r.training_done else 0
        tot["app_days"] += 1 if r.app_updated else 0
        tot["stock_var"] += abs(r.stock_variance or 0)
        tot["stock_sold"] += r.stock_sold or 0
        tot["submissions"] += 1

    expected = max(len(active_ids) * days, 1)
    submission_rate = round(tot["submissions"] / expected * 100, 1)
    ranked = sorted(per.values(), key=lambda x: x["revenue"], reverse=True)
    kpis = {
        "total_revenue": round(tot["revenue"], 2),
        "units_sold": tot["units"],
        "total_walkins": tot["walk_ins"],
        "total_conversions": tot["conversions"],
        "conv_pct": _pct(tot["conversions"], tot["walk_ins"]),
        "calls_made": tot["calls"],
        "calls_connected": tot["connected"],
        "connect_rate_pct": _pct(tot["connected"], tot["calls"]),
        "care_plus_attached": tot["care_plus"],
        "complaints_in": tot["complaints_in"],
        "complaints_resolved": tot["complaints_resolved"],
        "complaint_resolution_pct": _pct(tot["complaints_resolved"], tot["complaints_in"]),
        "training_compliance_pct": round(tot["training_days"] / max(tot["submissions"], 1) * 100, 1),
        "submission_rate_pct": submission_rate,
        "store_count": len(per),
    }
    return {
        "kpis": kpis,
        "top": [{"name": s["name"], "value": s["revenue"], "sub": f"{s['conversions']} conv"} for s in ranked[:5]],
        "bottom": [{"name": s["name"], "value": s["revenue"], "sub": f"{s['conversions']} conv"} for s in ranked[-5:]],
        "highlights_auto": [
            f"Submission rate {submission_rate}% across {len(per)} stores" if tot["submissions"] else "No submissions this month",
            f"{kpis['conv_pct']}% walk-in conversion ({tot['conversions']}/{tot['walk_ins']})" if tot["walk_ins"] else None,
            f"{tot['care_plus']} Care+ attachments" if tot["care_plus"] else None,
        ],
        "concerns_auto": [
            f"{kpis['complaint_resolution_pct']}% complaints resolved ({tot['complaints_resolved']}/{tot['complaints_in']})" if tot["complaints_in"] else None,
            f"Stock variance of {tot['stock_var']} units" if tot["stock_var"] else None,
        ],
    }


async def _team_leaders_context(db: AsyncSession, month: str) -> dict:
    """Revenue/target come from the MCP-backed report (get_sales_report),
    not a DailySubmission-only sum — that used to silently miss every
    non-India team leader's stores entirely, plus any India store whose
    revenue only ever arrived via MCP with no manual Sheets submission."""
    start, end = _month_range(month)
    today = date.today()
    tl_report = await get_sales_report(
        db, granularity="day", start=start.isoformat(), end=min(end, today).isoformat(), group_by="team_leader",
    )
    ranked = [
        {"name": t["key"], "revenue": t["revenue"], "target": t["target"], "stores": t["store_count"]}
        for t in sorted(tl_report["breakdown"], key=lambda x: x["revenue"], reverse=True)
    ]

    total_rev = round(sum(t["revenue"] for t in ranked), 2)
    total_target = round(sum(t["target"] for t in ranked), 2)
    for t in ranked:
        t["ach_pct"] = _pct(t["revenue"], t["target"])
    kpis = {
        "tl_count": len(ranked),
        "total_revenue": total_rev,
        "total_target": total_target,
        "achievement_pct": _pct(total_rev, total_target),
        "top_tl": ranked[0]["name"] if ranked else None,
        "top_tl_ach_pct": ranked[0]["ach_pct"] if ranked else 0,
        "bottom_tl": ranked[-1]["name"] if ranked else None,
        "bottom_tl_ach_pct": ranked[-1]["ach_pct"] if ranked else 0,
    }
    return {
        "kpis": kpis,
        "top": [{"name": t["name"], "value": t["revenue"], "sub": f"{t['ach_pct']}% · {t['stores']} stores", "ach_pct": t["ach_pct"]} for t in ranked[:5]],
        "bottom": [{"name": t["name"], "value": t["revenue"], "sub": f"{t['ach_pct']}% · {t['stores']} stores", "ach_pct": t["ach_pct"]} for t in ranked[-3:]],
        "highlights_auto": [
            f"Top TL: {kpis['top_tl']} at {kpis['top_tl_ach_pct']}%" if kpis["top_tl"] else None,
            f"{len(ranked)} team leaders across the network",
        ],
        "concerns_auto": [
            f"Bottom TL: {kpis['bottom_tl']} at {kpis['bottom_tl_ach_pct']}%" if kpis["bottom_tl"] and kpis["bottom_tl_ach_pct"] < 50 else None,
        ],
    }


async def _leads_context(db: AsyncSession, month: str) -> dict:
    start, end = _month_range(month)
    start_dt = datetime(start.year, start.month, start.day)
    end_dt = datetime(end.year, end.month, end.day) + timedelta(days=1)
    leads = (await db.execute(
        select(Lead).where(Lead.created_at >= start_dt, Lead.created_at < end_dt)
    )).scalars().all()

    by_status = {}
    by_source = {}
    for l in leads:
        by_status[l.status] = by_status.get(l.status, 0) + 1
        by_source[l.source] = by_source.get(l.source, 0) + 1

    subs = (await db.execute(
        select(func.sum(DailySubmission.calls_made), func.sum(DailySubmission.calls_connected),
               func.sum(DailySubmission.walk_ins), func.sum(DailySubmission.walk_in_conversions))
        .where(DailySubmission.date >= start, DailySubmission.date <= end)
    )).one()
    calls = _num(subs[0]); connected = _num(subs[1]); walkins = _num(subs[2]); conv = _num(subs[3])

    lost_rows = (await db.execute(
        select(LostReason.reason, func.sum(LostReason.count))
        .where(LostReason.date >= start, LostReason.date <= end)
        .group_by(LostReason.reason).order_by(func.sum(LostReason.count).desc())
    )).all()
    lost = [{"reason": r[0], "count": int(r[1])} for r in lost_rows]
    lost_total = sum(l["count"] for l in lost)

    kpis = {
        "total_leads": len(leads),
        "hot": by_status.get("hot", 0),
        "warm": by_status.get("warm", 0),
        "cold": by_status.get("cold", 0),
        "inactive": by_status.get("inactive", 0),
        "calls_made": int(calls),
        "calls_connected": int(connected),
        "connect_rate_pct": _pct(connected, calls),
        "walk_ins": int(walkins),
        "conversions": int(conv),
        "conv_pct": _pct(conv, walkins),
        "lost_total": lost_total,
        "top_source": max(by_source, key=by_source.get) if by_source else None,
    }
    return {
        "kpis": kpis,
        "top": [{"name": s, "value": v, "sub": "leads by source"} for s, v in sorted(by_source.items(), key=lambda x: x[1], reverse=True)[:5]],
        "highlights_auto": [
            f"{len(leads)} new leads this month" if len(leads) else None,
            f"{kpis['conv_pct']}% walk-in conversion ({int(conv)}/{int(walkins)})" if walkins else None,
            f"{kpis['connect_rate_pct']}% call connect rate" if calls else None,
        ],
        "concerns_auto": [
            f"{lost_total} lost leads recorded" if lost_total else None,
            f"{by_status.get('cold', 0)} cold + {by_status.get('inactive', 0)} inactive leads" if by_status.get("cold") or by_status.get("inactive") else None,
        ],
        "lost_reasons": lost,
    }


async def _campaigns_context(db: AsyncSession, month: str) -> dict:
    campaigns = (await db.execute(select(Campaign))).scalars().all()
    today = date.today()

    by_status = {}
    by_channel = {}
    budget = 0.0
    success = []
    running = upcoming = expired = 0
    for c in campaigns:
        st = c.status or "draft"
        by_status[st] = by_status.get(st, 0) + 1
        by_channel[c.channel or "other"] = by_channel.get(c.channel or "other", 0) + 1
        budget += _num(c.budget)
        if c.success_rate:
            success.append(_num(c.success_rate))
        if st in ("active", "running") or (c.start_date and c.end_date and c.start_date <= today <= c.end_date):
            running += 1
        if c.start_date and c.start_date > today:
            upcoming += 1
        if c.end_date and c.end_date < today and st not in ("completed",):
            expired += 1

    kpis = {
        "total_campaigns": len(campaigns),
        "running": running,
        "upcoming": upcoming,
        "expired": expired,
        "total_budget": round(budget, 2),
        "avg_success_rate": round(sum(success) / len(success), 1) if success else 0,
        "channels": len(by_channel),
        "top_channel": max(by_channel, key=by_channel.get) if by_channel else None,
    }
    ranked = sorted(campaigns, key=lambda c: _num(c.budget), reverse=True)[:5]
    return {
        "kpis": kpis,
        "top": [{"name": c.name, "value": _num(c.budget), "sub": f"{c.channel} · {c.status}"} for c in ranked],
        "by_channel": [
            {"name": ch, "count": c} for ch, c in sorted(by_channel.items(), key=lambda x: x[1], reverse=True)
        ],
        "highlights_auto": [
            f"{running} campaigns running now" if running else None,
            f"Average success rate {kpis['avg_success_rate']}%" if success else None,
        ],
        "concerns_auto": [
            f"{expired} campaigns past their end date" if expired else None,
            f"Total budget ₹{budget:,.0f} across {len(campaigns)} campaigns" if len(campaigns) else None,
        ],
    }


async def _tasks_context(db: AsyncSession, month: str) -> dict:
    tasks = (await db.execute(select(Task))).scalars().all()
    now = datetime.now()

    by_status = {}
    by_priority = {}
    overdue = 0
    for t in tasks:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
        if t.due_at and t.due_at < now and t.status != "completed":
            overdue += 1

    total = len(tasks)
    completed = by_status.get("completed", 0)
    kpis = {
        "total_tasks": total,
        "pending": by_status.get("pending", 0),
        "in_progress": by_status.get("in_progress", 0),
        "completed": completed,
        "completed_pct": round(completed / total * 100, 1) if total else 0,
        "overdue": overdue,
        "high_priority": by_priority.get("high", 0),
        "medium_priority": by_priority.get("medium", 0),
        "low_priority": by_priority.get("low", 0),
    }
    open_tasks = [t for t in tasks if t.status != "completed"]
    overdue_tasks = [t for t in open_tasks if t.due_at and t.due_at < now]
    return {
        "kpis": kpis,
        "top": [{"name": t.title, "value": 0, "sub": f"{t.status} · {t.priority}"} for t in overdue_tasks[:5]],
        "highlights_auto": [
            f"{completed} of {total} tasks completed" if total else None,
            f"{by_priority.get('high', 0)} high-priority tasks tracked" if by_priority.get("high") else None,
        ],
        "concerns_auto": [
            f"{overdue} overdue tasks" if overdue else None,
            f"{by_status.get('pending', 0)} tasks still pending" if by_status.get("pending") else None,
        ],
    }


async def _investments_context(db: AsyncSession, month: str) -> dict:
    investments = (await db.execute(select(Investment))).scalars().all()
    start, end = _month_range(month)
    prev_start = start - timedelta(days=(end - start).days + 1)
    prev_end = start - timedelta(days=1)

    by_cat = {}
    by_store = {}
    total = 0.0
    this_month = 0.0
    prev_month = 0.0
    for inv in investments:
        amt = _num(inv.amount)
        total += amt
        by_cat[inv.category] = by_cat.get(inv.category, 0.0) + amt
        by_store[inv.store_id] = by_store.get(inv.store_id, 0.0) + amt
        if start <= inv.date <= end:
            this_month += amt
        elif prev_start <= inv.date <= prev_end:
            prev_month += amt

    delta_pct = round((this_month - prev_month) / prev_month * 100, 1) if prev_month > 0 else 0
    top_cat = max(by_cat, key=by_cat.get) if by_cat else None
    kpis = {
        "total_invested": round(total, 2),
        "investment_count": len(investments),
        "this_month": round(this_month, 2),
        "prev_month": round(prev_month, 2),
        "mo_delta_pct": delta_pct,
        "categories": len(by_cat),
        "top_category": top_cat,
    }
    return {
        "kpis": kpis,
        "top": [{"name": c, "value": v, "sub": "by category"} for c, v in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:5]],
        "highlights_auto": [
            f"₹{this_month:,.0f} invested this month" if this_month else None,
            f"Top category: {top_cat} (₹{by_cat[top_cat]:,.0f})" if top_cat else None,
        ],
        "concerns_auto": [
            f"Spend {delta_pct}% vs last month" if prev_month > 0 and delta_pct > 50 else None,
            f"{len(investments)} total investments logged" if len(investments) else None,
        ],
    }


def _resolve_band(score: float, bands: list):
    sorted_bands = sorted(bands, key=lambda b: b.min_kpi_score, reverse=True)
    for band in sorted_bands:
        if score >= float(band.min_kpi_score):
            return band.label
    return "Below Target"


async def _performance_context(db: AsyncSession, month: str) -> dict:
    """The revenue side of each store's score comes from the MCP-backed
    report (get_sales_report), not a DailySubmission-only sum — that used
    to understate/zero a store's revenue_vs_target component whenever its
    real revenue only ever arrived via MCP sync. The other components here
    (walk-ins, calls, stock, training, complaints) are genuinely
    Sheets-only concepts with no MCP equivalent, so they're unaffected and
    still require an actual Sheets submission to exist."""
    start, end = _month_range(month)
    today = date.today()
    weights = {k.kpi_name: _num(k.weight) for k in (await db.execute(select(KPIWeight))).scalars().all()}
    bands = (await db.execute(select(IncentiveBand))).scalars().all()
    stores = (await db.execute(select(Store).where(Store.is_active == True))).scalars().all()
    days = (end - start).days + 1

    branch_report = await get_sales_report(
        db, granularity="day", start=start.isoformat(), end=min(end, today).isoformat(), group_by="branch",
    )
    mcp_by_name = {b["key"]: b for b in branch_report["breakdown"]}

    metric_sums = {}
    band_counts = {}
    scores = []
    for store in stores:
        subs = (await db.execute(
            select(DailySubmission).where(
                DailySubmission.store_id == store.id,
                DailySubmission.date >= start, DailySubmission.date <= end,
            )
        )).scalars().all()
        if not subs:
            continue
        mcp = mcp_by_name.get(store.name)
        total_rev = mcp["revenue"] if mcp else sum(_num(s.revenue) for s in subs)
        target = mcp["target"] if mcp else _num(store.monthly_target) * days / 30
        total_walk = sum(s.walk_ins for s in subs)
        total_conv = sum(s.walk_in_conversions for s in subs)
        total_calls = sum(s.calls_made for s in subs)
        stock_sold = sum(s.stock_sold for s in subs)
        stock_var = sum(abs(s.stock_variance) for s in subs)
        total_complaints = sum(s.complaints_in for s in subs)
        total_resolved = sum(s.complaints_resolved for s in subs)
        trained = sum(1 for s in subs if s.training_done)
        app_updated = sum(1 for s in subs if s.app_updated)

        m = {
            "revenue_vs_target": (_num(total_rev) / target) if target > 0 else 0,
            "dsr_submission_rate": min(len(subs) / days, 1.0),
            "walk_in_conversion": (_num(total_conv) / _num(total_walk)) if total_walk > 0 else 0,
            "calls_vs_target": min(_num(total_calls) / (days * 50), 1.0),
            "stock_control": max(0.0, 1.0 - (_num(stock_var) / max(_num(stock_sold), 1))),
            "training_compliance": trained / max(len(subs), 1),
            "bp_app_update_rate": app_updated / max(len(subs), 1),
            "complaint_resolution": (_num(total_resolved) / _num(total_complaints)) if total_complaints > 0 else 1.0,
        }
        total_score = sum(m.get(k, 0) * v for k, v in weights.items())
        label = _resolve_band(total_score, bands)
        band_counts[label] = band_counts.get(label, 0) + 1
        scores.append({"store": store.name, "score": total_score, "band": label})
        for k, v in m.items():
            metric_sums[k] = metric_sums.get(k, 0.0) + v

    n = len(scores)
    metric_avgs = {k: round(v / n, 3) for k, v in metric_sums.items()} if n else {}
    weakest = min(metric_avgs, key=metric_avgs.get) if metric_avgs else None
    kpis = {
        "store_count": n,
        "avg_total_score": round(sum(s["score"] for s in scores) / n, 1) if n else 0,
        "exceeds": band_counts.get("Exceeds Target", 0),
        "meets": band_counts.get("Meets Target", 0),
        "approaching": band_counts.get("Approaching Target", 0),
        "below": band_counts.get("Below Target", 0),
        "weakest_metric": weakest,
    }
    return {
        "kpis": kpis,
        "top": [{"name": s["store"], "value": s["score"], "sub": s["band"]} for s in sorted(scores, key=lambda x: x["score"], reverse=True)[:5]],
        "bottom": [{"name": s["store"], "value": s["score"], "sub": s["band"]} for s in sorted(scores, key=lambda x: x["score"])[:3]],
        "metric_averages": metric_avgs,
        "highlights_auto": [
            f"{kpis['exceeds']} stores exceeding target band" if kpis["exceeds"] else None,
            f"Average score {kpis['avg_total_score']} across {n} stores" if n else None,
        ],
        "concerns_auto": [
            f"{kpis['below']} stores below target band" if kpis["below"] else None,
            f"Weakest metric: {weakest}" if weakest else None,
        ],
    }


async def _reports_context(db: AsyncSession, month: str) -> dict:
    start, end = _month_range(month)
    stores = (await db.execute(select(Store).where(Store.is_active == True))).scalars().all()
    tl_names = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}

    rev_map = {}
    unit_map = {}
    if stores:
        rows = (await db.execute(
            select(DailySubmission.store_id, func.sum(DailySubmission.revenue), func.sum(DailySubmission.units_sold))
            .where(DailySubmission.date >= start, DailySubmission.date <= end)
            .group_by(DailySubmission.store_id)
        )).all()
        rev_map = {r[0]: _num(r[1]) for r in rows}
        unit_map = {r[0]: int(r[2] or 0) for r in rows}

    per_store = []
    for s in stores:
        per_store.append({
            "name": s.name, "tl": tl_names.get(s.team_leader_id, "Unassigned"),
            "revenue": rev_map.get(s.id, 0.0), "units": unit_map.get(s.id, 0),
            "target": _num(s.monthly_target),
        })
    for p in per_store:
        p["ach_pct"] = _pct(p["revenue"], p["target"])

    per_store.sort(key=lambda x: x["revenue"], reverse=True)
    total_rev = round(sum(p["revenue"] for p in per_store), 2)
    total_target = round(sum(p["target"] for p in per_store), 2)

    lost_rows = (await db.execute(
        select(LostReason.reason, func.sum(LostReason.count))
        .where(LostReason.date >= start, LostReason.date <= end)
        .group_by(LostReason.reason).order_by(func.sum(LostReason.count).desc())
    )).all()
    lost = [{"reason": r[0], "count": int(r[1])} for r in lost_rows]

    kpis = {
        "total_revenue": total_rev,
        "total_target": total_target,
        "achievement_pct": _pct(total_rev, total_target),
        "total_stores": len(per_store),
        "units_sold": sum(p["units"] for p in per_store),
        "top_store": per_store[0]["name"] if per_store else None,
        "top_store_ach_pct": per_store[0]["ach_pct"] if per_store else 0,
        "bottom_store": per_store[-1]["name"] if per_store else None,
        "bottom_store_ach_pct": per_store[-1]["ach_pct"] if per_store else 0,
        "lost_reason_total": sum(l["count"] for l in lost),
    }
    return {
        "kpis": kpis,
        "top": [{"name": p["name"], "value": p["revenue"], "sub": f"{p['ach_pct']}% · {p['tl']}", "ach_pct": p["ach_pct"]} for p in per_store[:5]],
        "bottom": [{"name": p["name"], "value": p["revenue"], "sub": f"{p['ach_pct']}% · {p['tl']}", "ach_pct": p["ach_pct"]} for p in per_store[-3:]],
        "lost_reasons": lost,
        "highlights_auto": [
            f"Top store: {kpis['top_store']} at {kpis['top_store_ach_pct']}%" if kpis["top_store"] else None,
            f"₹{total_rev:,.0f} revenue against ₹{total_target:,.0f} target" if total_rev else None,
        ],
        "concerns_auto": [
            f"Bottom store: {kpis['bottom_store']} at {kpis['bottom_store_ach_pct']}%" if kpis["bottom_store"] and kpis["bottom_store_ach_pct"] < 35 else None,
            f"{kpis['lost_reason_total']} lost leads logged" if kpis["lost_reason_total"] else None,
        ],
    }


# ── Registry ───────────────────────────────────────────────────────────────
SECTION_BUILDERS = {
    "sales": _sales_context,
    "operations": _operations_context,
    "team_leaders": _team_leaders_context,
    "leads": _leads_context,
    "campaigns": _campaigns_context,
    "tasks": _tasks_context,
    "investments": _investments_context,
    "performance": _performance_context,
    "reports": _reports_context,
}

SECTION_TITLES = {
    "sales": "Store Overview",
    "operations": "Operations",
    "team_leaders": "Team Leaders",
    "leads": "Leads",
    "campaigns": "Campaigns",
    "tasks": "Tasks",
    "investments": "Investments",
    "performance": "Performance",
    "reports": "Reports",
}

SECTION_VIEW_RESOURCE = {
    "sales": "dashboard",
    "operations": "operations",
    "team_leaders": "team_leaders",
    "leads": "leads",
    "campaigns": "campaigns",
    "tasks": "tasks",
    "investments": "investments",
    "performance": "performance",
    "reports": "reports",
}

SECTION_DEFAULT_PROMPTS = {
    "sales": _make_prompt(
        "You are the Sales Director of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Store Overview tab. This is a revenue briefing, not a general summary. "
        "Analyse the provided JSON snapshot and lead with the gap between revenue and target, current pace and projected "
        "month-end, and the achievement split across stores. "
        "Output style: frame the summary as 'sales momentum and target gap'; recommendations must be actions that close "
        "the revenue gap (push best-performing stores harder, fix laggards, rebalance targets); anomalies must flag "
        "stores where pace is materially below target. "
        "The JSON includes prior_month_comparison (revenue_change_pct vs last month) and detected_issues (real, "
        "rule-detected problems already found in the data) — reference these directly instead of re-deriving your own "
        "guesses; if detected_issues is non-empty, at least one anomaly or recommendation must address one of them by name. "
        "Use exact store and TL names and numbers, never invent data."
    ),
    "operations": _make_prompt(
        "You are the Retail Operations Manager of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Operations tab. This is a store-execution health report, not a finance review. "
        "Analyse the provided JSON snapshot and lead with submission discipline and daily execution: walk-ins, conversion, "
        "Care+ attachment, complaints resolution, stock variance and training compliance. "
        "Output style: frame the summary as 'operational discipline and compliance'; recommendations must be process-level "
        "fixes (training, re-checks, SOP compliance, stock reconciliation); anomalies must flag stores with low submission "
        "rates, unresolved complaints or stock variance. "
        "Use exact store names and numbers, never invent data."
    ),
    "team_leaders": _make_prompt(
        "You are the Sales Force Manager of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Team Leaders tab. This is a leadership scorecard, not a company overview. "
        "Analyse the provided JSON snapshot and rank each team leader by revenue vs target and achievement %, noting how "
        "many stores each leads. "
        "Output style: frame the summary around the leadership ranking ('the leadership pack'); highlights must call out "
        "top TLs; recommendations must be coaching actions addressed to specific TLs and their stores; anomalies must flag "
        "leaders consistently below target. "
        "Use exact TL and store names and numbers, never invent data."
    ),
    "leads": _make_prompt(
        "You are the CRM and Pipeline Analyst of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Leads tab. This is a lead-funnel health briefing, not a revenue report. "
        "Analyse the provided JSON snapshot and lead with pipeline movement: new leads by status (hot/warm/cold/inactive), "
        "top sources, call connect rate, walk-in conversion and lost reasons. "
        "Output style: frame the summary as 'pipeline health and leakage'; highlights must call out growing sources or "
        "strong conversion; recommendations must be nurture/qualification/follow-up actions by segment; anomalies must flag "
        "lost-lead spikes or stagnant cold/inactive pools. "
        "Use exact numbers, source names and reason labels, never invent data."
    ),
    "campaigns": _make_prompt(
        "You are the Marketing Performance Analyst of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Campaigns tab. This is a media-mix and budget review, not a sales briefing. "
        "Analyse the provided JSON snapshot and lead with budget allocation by channel, which campaigns are running, "
        "upcoming or expired, and the average success rate. "
        "Output style: frame the summary as 'campaign mix and spend efficiency'; highlights must call out effective "
        "channels; recommendations must be budget reallocation and campaign calendar actions by name; anomalies must flag "
        "expired or over-budget campaigns. "
        "Use exact campaign names, channels and amounts, never invent data."
    ),
    "tasks": _make_prompt(
        "You are the Operations Coordinator of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Tasks tab. This is a workload and follow-through report, not a performance review. "
        "Analyse the provided JSON snapshot and lead with completion rate, open tasks by status and priority, and overdue "
        "items. "
        "Output style: frame the summary as 'workload and follow-through'; recommendations must be concrete prioritization "
        "and owner assignment actions by task title; anomalies must flag overdue high-priority tasks and team overload. "
        "Use exact task titles, priorities and statuses, never invent data."
    ),
    "investments": _make_prompt(
        "You are the Finance Analyst of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Investments tab. This is a spend and allocation review, not an operational report. "
        "Analyse the provided JSON snapshot and lead with total invested, spend by category and store, and the "
        "month-over-month trend. "
        "Output style: frame the summary as 'capital allocation and spend discipline'; recommendations must be "
        "cost-control or reallocation actions by category; anomalies must flag outsized spend, steep MoM increases, or "
        "concentrated allocation. "
        "Use exact categories and amounts, never invent data."
    ),
    "performance": _make_prompt(
        "You are the KPI and Incentive Analyst of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Performance tab. This is a store scorecard review, not a revenue summary. "
        "Analyse the provided JSON snapshot and lead with the average KPI score, the band distribution (exceeds / meets / "
        "approaching / below target) and the weakest metrics dragging scores down. "
        "Output style: frame the summary as 'scorecard and incentive readiness'; recommendations must be targeted "
        "interventions per store or metric to move scores up a band; anomalies must flag stores in the below-target band. "
        "Use exact store names, scores and metric names, never invent data."
    ),
    "reports": _make_prompt(
        "You are the Reporting Analyst of BreakProtection, a multi-store retail chain in India, UAE and Oman. "
        "You are reviewing the Reports tab. This is the monthly report narrative, a consolidated leaderboard of stores "
        "with achievement and lost-lead reasons. "
        "Analyse the provided JSON snapshot and lead with the top and bottom performers, overall achievement vs target, "
        "and the recurring lost-reason drivers. "
        "Output style: frame the summary as a polished month-end report for leadership; recommendations must be "
        "forward-looking actions for the next month by store/TL; anomalies must flag the bottom performers and dominant "
        "lost-lead reasons. "
        "Use exact store, TL names, percentages and amounts, never invent data."
    ),
}


async def build_section_context(db: AsyncSession, section: str, month: str) -> dict:
    if section == "overview":
        from .ai_summary_service import build_dashboard_context

        return await build_dashboard_context(db, month)
    builder = SECTION_BUILDERS.get(section)
    if builder is None:
        raise ValueError(f"Unknown AI section: {section}")
    return await builder(db, month)
