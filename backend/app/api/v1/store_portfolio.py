"""One store's complete performance portfolio for a date range: social media
(Daily Tracker sheet), leads & conversions (CRM), sales (MCP) and Google
reviews, with targets, pace and an automatic action plan.

Also the per-store lead / conversion targets the portfolio measures against
(company default + optional per-store override, kept in Settings)."""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db, require_permission
from ...core.store_scope import allowed_store_ids, check_store
from ...models.models import (
    DailyStoreTracker, DailySubmission, GoogleReview, McpDailySale, Setting, Store,
    StoreMcpAlias, StoreWalkin, TeleAppointment, TeleCallLead, TeleLeadActivity, User,
)
from ...services import sales_report_service
from ...services.crm import metrics as crm_metrics
from ...services.crm.engine import parse_amount
from ...services.crm.status import NO_STATUS
from ...services.store_portfolio import (
    AREA_LABELS, DEFAULT_LEAD_TARGETS, LEAD_SOURCES, SHEET_AREA, analyse, area_of_sheet, area_of_store,
    attribute_lead, best_of, shop_of_sheet, days_in_month, group_duplicates, lead_source_bucket, pace, prorated_target,
    shop_of, shops_mentioned,
)
from .crm import source_key
from .social import PLATFORM_VIEWS, _default_targets, _target_overrides

router = APIRouter(prefix="/store-portfolio", tags=["store-portfolio"])

MAX_RANGE_DAYS = 366
LEAD_TARGETS_KEY = "store_lead_targets"
WARM_STATUSES = {"Will Visit", "Appointment", "Call back later"}
# Country -> currency, for stores whose currency_code was never set.
COUNTRY_CURRENCY = {"India": "INR", "UAE": "AED", "Oman": "OMR", "Qatar": "QAR", "Pakistan": "PKR",
                    "Malaysia": "MYR", "UK": "GBP", "Bahrain": "BHD"}
CURRENCY_SYMBOL = {"INR": "₹", "GBP": "£", "USD": "$"}


# ── Lead targets (settings) ─────────────────────────────────────────
async def _lead_targets(db: AsyncSession) -> dict:
    row = (await db.execute(select(Setting).where(Setting.key == LEAD_TARGETS_KEY))).scalar_one_or_none()
    try:
        data = json.loads(row.value) if row and row.value else {}
    except (TypeError, ValueError):
        data = {}
    return {
        "default": {**DEFAULT_LEAD_TARGETS, **(data.get("default") or {})},
        "stores": {int(k): v for k, v in (data.get("stores") or {}).items()},
    }


def _store_lead_target(targets: dict, store_id: int) -> dict:
    own = targets["stores"].get(store_id) or {}
    return {k: own[k] if own.get(k) is not None else targets["default"][k] for k in DEFAULT_LEAD_TARGETS}


@router.get("/lead-targets")
async def get_lead_targets(
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("settings", "view"),
):
    targets = await _lead_targets(db)
    stores = (await db.execute(
        select(Store, User.name).outerjoin(User, Store.team_leader_id == User.id)
        .where(Store.is_active == True).order_by(Store.name)  # noqa: E712
    )).all()
    return {
        "defaults": targets["default"],
        "stores": [
            {"store_id": s.id, "store": s.name, "country": s.country or "", "team_leader": tl or "",
             "overrides": {k: (targets["stores"].get(s.id) or {}).get(k) for k in DEFAULT_LEAD_TARGETS}}
            for s, tl in stores
        ],
    }


class LeadTargetValues(BaseModel):
    leads_monthly: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    conversion_pct: Optional[float] = Field(default=None, ge=0, le=100)


class LeadTargetOverride(LeadTargetValues):
    store_id: int


class LeadTargetsUpdate(BaseModel):
    defaults: Optional[LeadTargetValues] = None
    overrides: list[LeadTargetOverride] = []


@router.put("/lead-targets")
async def update_lead_targets(
    body: LeadTargetsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("settings", "edit"),
):
    targets = await _lead_targets(db)
    if body.defaults:
        for k, v in body.defaults.model_dump().items():
            if v is not None:
                targets["default"][k] = v
    for o in body.overrides:
        values = {k: v for k, v in o.model_dump(exclude={"store_id"}).items() if v is not None}
        if values:
            targets["stores"][o.store_id] = values
        else:  # both blank = back to the default
            targets["stores"].pop(o.store_id, None)
    value = json.dumps({"default": targets["default"], "stores": {str(k): v for k, v in targets["stores"].items()}})
    row = (await db.execute(select(Setting).where(Setting.key == LEAD_TARGETS_KEY))).scalar_one_or_none()
    if row:
        row.value, row.updated_by = value, user.id
    else:
        db.add(Setting(key=LEAD_TARGETS_KEY, value=value, updated_by=user.id))
    await db.commit()
    return {"ok": True}


# ── Portfolio ───────────────────────────────────────────────────────
def _money_formatter(currency: str):
    symbol = CURRENCY_SYMBOL.get(currency, f"{currency} ")

    def fmt(x: float) -> str:
        x = round(x or 0)
        if currency == "INR":  # Indian grouping: 2,80,000
            s = str(abs(x))
            head, tail = s[:-3], s[-3:]
            while len(head) > 2:
                tail, head = head[-2:] + "," + tail, head[:-2]
            s = (head + "," + tail) if head else tail
            return f"{'-' if x < 0 else ''}{symbol}{s}"
        return f"{symbol}{x:,}"
    return fmt


async def _sales(db: AsyncSession, store: Store, start: date, end: date, today: date) -> dict:
    synced_end = min(end, today)
    if start <= synced_end:
        await sales_report_service._ensure_mcp_coverage(db, start, synced_end)
    rows = (await db.execute(
        select(McpDailySale).where(McpDailySale.store_id == store.id,
                                   McpDailySale.date >= start, McpDailySale.date <= end)
        .order_by(McpDailySale.date)
    )).scalars().all()
    # Same rule as the sales report: the target is MCP's, so only trusted for
    # stores MCP actually maintains (have an alias).
    has_alias = (await db.execute(
        select(func.count(StoreMcpAlias.id)).where(StoreMcpAlias.store_id == store.id)
    )).scalar() or 0
    monthly = float(store.monthly_target or 0) if has_alias else 0.0

    by_day = defaultdict(float)
    sales_count = units = 0
    for r in rows:
        by_day[r.date] += float(r.revenue or 0)
        sales_count += r.new_sale_count or 0
        units += r.units_sold or 0
    revenue = sum(by_day.values())
    p = pace(monthly, revenue, start, end, today)
    bill_count = sales_count or units
    avg_bill = revenue / bill_count if bill_count else 0.0

    series, cum, d = [], 0.0, start
    daily_target = p.target / p.days_total if p.days_total else 0
    while d <= end:
        if d <= today:
            cum += by_day.get(d, 0.0)
        series.append({
            "date": d.isoformat(),
            "revenue": round(by_day.get(d, 0.0), 2) if d <= today else None,
            "cumulative": round(cum, 2) if d <= today else None,
            "target_pace": round(prorated_target(monthly, start, d), 2),
        })
        d += timedelta(days=1)
    synced = (await db.execute(
        select(func.max(McpDailySale.synced_at)).where(McpDailySale.store_id == store.id)
    )).scalar()
    return {
        "monthly_target": monthly,
        "pace": p.as_dict(),
        "sales_count": sales_count,
        "units": units,
        "avg_bill": round(avg_bill, 2),
        "sales_needed": round(p.remaining / avg_bill) if avg_bill and p.remaining else 0,
        "daily_target": round(daily_target, 2),
        "series": series,
        "last_synced_at": synced.isoformat() + "Z" if synced else None,
    }


async def _tracker_months(db: AsyncSession, store_id: int, end: date, months: int = 6) -> list[DailyStoreTracker]:
    """The store's Daily Tracker figures, one row per calendar month, for up
    to `months` months ending with `end`'s month.

    The sheet holds a month-to-date row per store ("01 to 15-Oct-2026",
    stored as its last day). When the store moves that row on to the 20th,
    the sync keeps the old row too, so only the latest row of each month is
    the month's figure — summing them would double count."""
    first = date(end.year, end.month, 1)
    for _ in range(months - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    rows = (await db.execute(
        select(DailyStoreTracker).where(
            DailyStoreTracker.store_id == store_id,
            DailyStoreTracker.date.like("____-__-__"),
            DailyStoreTracker.date >= first.isoformat(), DailyStoreTracker.date <= end.isoformat(),
        ).order_by(DailyStoreTracker.date)
    )).scalars().all()
    latest: dict[str, DailyStoreTracker] = {}
    for r in rows:  # ascending, so the month's last row wins
        latest[r.date[:7]] = r
    return list(latest.values())


def _in_range(rows: list[DailyStoreTracker], start: date, end: date) -> list[DailyStoreTracker]:
    return [r for r in rows if start.isoformat() <= r.date <= end.isoformat()]


async def _social(db: AsyncSession, store: Store, history: list[DailyStoreTracker],
                  start: date, end: date, today: date) -> dict:
    defaults = await _default_targets(db)
    overrides = (await _target_overrides(db, [store.id])).get(store.id, {})
    targets = {p: overrides.get(p, defaults[p]) for p in PLATFORM_VIEWS}
    rows = _in_range(history, start, end)
    as_of = date.fromisoformat(rows[-1].date) if rows else None

    totals = {p: sum(float(getattr(r, col) or 0) for r in rows) for p, col in PLATFORM_VIEWS.items()}
    eng = {k: sum(getattr(r, k) or 0 for r in rows) for k in (
        "ig_videos_posted", "ig_likes", "ig_comments", "ig_shares", "ig_saves", "ig_reposts",
        "ig_new_followers", "ig_posts_published", "ig_dms_received", "wa_chats_received")}
    has_ig = any((r.ig_videos_posted or r.ig_views_achieved or r.ig_followers or r.ig_posts_published) for r in rows)
    platforms = {}
    for p in PLATFORM_VIEWS:
        has = has_ig if p == "instagram" else totals[p] > 0
        platforms[p] = {"has_data": has, "monthly_target": targets[p],
                        **pace(targets[p], totals[p], start, end, today, as_of=as_of).as_dict()}

    # Month by month, for the chart and for "last reported" when the
    # selected period has nothing yet (e.g. early in a new month).
    monthly = []
    for r in history:
        d = date.fromisoformat(r.date)
        m_start = d.replace(day=1)
        row = {"month": r.date[:7], "as_of": r.date}
        for p, col in PLATFORM_VIEWS.items():
            views = float(getattr(r, col) or 0)
            expected = prorated_target(targets[p], m_start, d)
            row[p] = views
            row[f"{p}_target"] = round(expected)
            row[f"{p}_pct"] = round(views / expected * 100, 1) if expected else None
        row["reels"] = r.ig_videos_posted or 0
        monthly.append(row)

    latest = rows[-1] if rows else None
    return {
        "has_data": bool(rows) and has_ig,
        "as_of": as_of.isoformat() if as_of else None,
        "platforms": platforms,
        "views": platforms["instagram"],
        "reels": eng["ig_videos_posted"],
        "posts": eng["ig_posts_published"],
        "likes": eng["ig_likes"],
        "comments": eng["ig_comments"],
        "shares": eng["ig_shares"],
        "saves": eng["ig_saves"],
        "reposts": eng["ig_reposts"],
        "new_followers": eng["ig_new_followers"],
        "followers": latest.ig_followers if latest else 0,
        "dms": eng["ig_dms_received"],
        "wa_chats": eng["wa_chats_received"],
        "monthly": monthly,
        "last_report": monthly[-1] if monthly and not rows else None,
    }


def _review_extras(rows: list[DailyStoreTracker]) -> dict:
    """Sum (or, for "total ..." columns, take the latest of) every extra
    Google/review column the sheet has, and pick out positive / negative /
    unanswered counts when such columns exist."""
    values: dict[str, float | str] = {}
    for r in rows:
        for label, v in (r.extra_fields or {}).items():
            if isinstance(v, (int, float)) and "total" not in label.lower() and "rating" not in label.lower():
                values[label] = float(values.get(label, 0) or 0) + v
            else:
                values[label] = v
    picked: dict[str, Optional[float]] = {"positive": None, "negative": None, "unanswered": None}
    for label, v in values.items():
        low = label.lower()
        if not isinstance(v, (int, float)):
            continue
        key = ("unanswered" if any(w in low for w in ("unanswer", "not replied", "no reply", "pending"))
               else "negative" if "negative" in low else "positive" if "positive" in low else None)
        if key:
            picked[key] = (picked[key] or 0) + v
    return {"columns": values, **picked}


async def _reviews(db: AsyncSession, store: Store, history: list[DailyStoreTracker],
                   start: date, end: date) -> dict:
    rows = _in_range(history, start, end)
    # Rating is a point-in-time figure: the latest one reported up to `end`,
    # even if that was in an earlier month.
    rated = [r for r in history if r.google_rating]
    gr = (await db.execute(
        select(GoogleReview).where(GoogleReview.store_id == store.id, GoogleReview.date <= end)
        .order_by(GoogleReview.date.desc()).limit(1)
    )).scalar_one_or_none()
    if rated and (not gr or rated[-1].date >= gr.date.isoformat()):
        rating, rating_as_of = rated[-1].google_rating, rated[-1].date
    elif gr and gr.rating:
        rating, rating_as_of = gr.rating, gr.date.isoformat()
    else:
        rating, rating_as_of = None, None
    extras = _review_extras(rows)
    responses = [r.google_review_response for r in history if r.google_review_response]
    return {
        "rating": rating,
        "rating_as_of": rating_as_of,
        "rating_previous": rated[-2].google_rating if len(rated) > 1 else None,
        "new_reviews": sum(r.google_new_reviews or 0 for r in rows),
        "total_reviews": gr.total_reviews if gr else None,
        "response": responses[-1] if responses else "",
        "positive": extras["positive"],
        "negative": extras["negative"],
        "unanswered": extras["unanswered"],
        "extra_columns": extras["columns"],
    }


def _lead_figures(groups: list[list], conv_groups: list[list]) -> dict:
    """Counts for de-duplicated leads (each group is one person): `groups`
    arrived in the period, `conv_groups` bought in the period (whenever they
    arrived) — so a September lead who buys in October counts in October."""
    reps = [best_of(g) for g in groups]
    sources = {key: {"key": key, "label": label, "leads": 0, "converted": 0, "revenue": 0.0}
               for key, label, _ in LEAD_SOURCES}

    def bucket(g):
        first = g[0]  # where the person first came from
        return sources[lead_source_bucket(source_key(first), first.lead_source)]

    for g in groups:
        bucket(g)["leads"] += 1
    revenue = 0.0
    for g in conv_groups:
        amount = parse_amount(best_of(g).sale_amount)
        b = bucket(g)
        b["converted"] += 1
        b["revenue"] += amount
        revenue += amount
    for b in sources.values():
        b["rate"] = round(b["converted"] / b["leads"] * 100, 1) if b["leads"] else 0.0
        b["revenue"] = round(b["revenue"], 2)
        b["from"] = None
    kpis = crm_metrics.lead_kpis(reps)
    kpis["converted"] = len(conv_groups)
    kpis["conversion_pct"] = round(len(conv_groups) / len(groups) * 100, 1) if groups else 0.0
    kpis["total_sale_amount"] = revenue
    return {"kpis": kpis, "status_counts": crm_metrics.status_counts(reps), "sources": list(sources.values()),
            "merged": sum(len(g) - 1 for g in groups)}


CONVERSION_LOOKBACK_DAYS = 400  # a sale this period may come from a lead up to ~a year old


async def _conversion_times(db: AsyncSession, lead_ids: list[int]) -> dict[int, datetime]:
    """When each lead first became "Sale Conversion" (app, sheet or the MCP
    sale match all log it); leads converted before logging began have none."""
    if not lead_ids:
        return {}
    return dict((await db.execute(
        select(TeleLeadActivity.lead_id, func.min(TeleLeadActivity.created_at))
        .where(TeleLeadActivity.lead_id.in_(lead_ids), TeleLeadActivity.new_value == "Sale Conversion")
        .group_by(TeleLeadActivity.lead_id)
    )).all())


async def _leads(db: AsyncSession, store: Store, start: date, end: date, today: date) -> dict:
    """The store's leads, worked out at read time (see store_portfolio
    attribute_lead): its own shop's leads, plus its area's leads whose shop
    isn't known, shown separately. Duplicates count once. Leads received
    count by arrival date, conversions by the date of the sale."""
    all_stores = (await db.execute(select(Store.id, Store.name, Store.region, Store.is_active))).all()
    store_shop = {s.id: shop_of(s.name) for s in all_stores}
    target_shop = store_shop.get(store.id) or f"store:{store.id}"
    target_area = area_of_store(store.name, store.region or "")

    def shop_key(sid):
        """A store's shop; a placeholder record ("Kerala Store") counts as no
        store at all unless it's the store being viewed, so its leads fall
        to the area rules instead of vanishing."""
        if store_shop.get(sid):
            return store_shop[sid]
        return f"store:{sid}" if sid == store.id else None
    same_shop_ids = [s.id for s in all_stores if shop_key(s.id) == target_shop]
    area_shops = {store_shop[s.id] for s in all_stores
                  if s.is_active and store_shop[s.id] and area_of_store(s.name, s.region or "") == target_area}
    area_sheets = [sheet for sheet, area in SHEET_AREA.items() if target_area and area == target_area]

    p_start, p_end = crm_metrics.period_bounds(start, end)
    appt_lead_ids = select(TeleAppointment.lead_id).where(TeleAppointment.store_id.in_(same_shop_ids))
    candidates = or_(TeleCallLead.store_id.in_(same_shop_ids), TeleCallLead.id.in_(appt_lead_ids),
                     func.lower(TeleCallLead.sheet_tl_name).in_(area_sheets or ["-"]))
    arrived_at = lambda l: l.submitted_at or l.created_at  # noqa: E731
    how: dict[str, int] = defaultdict(int)

    async def split(leads: list, count_how: bool) -> tuple[list[list], list[list]]:
        """Group duplicates, then sort each person into this shop / the area pool."""
        appt_store = dict((await db.execute(
            select(TeleAppointment.lead_id, TeleAppointment.store_id)
            .where(TeleAppointment.lead_id.in_([l.id for l in leads] or [-1]), TeleAppointment.store_id.isnot(None))
            .order_by(TeleAppointment.scheduled_at)
        )).all())  # latest appointment wins
        mine, pool = [], []
        for g in group_duplicates(leads, arrived_at):
            # one person: use whatever any copy knows about the store
            sid = next((l.store_id for l in g if l.store_id), None)
            aid = next((appt_store[l.id] for l in reversed(g) if l.id in appt_store), None)
            remarks = set().union(*(shops_mentioned(" ".join(filter(None, (l.remarks, l.preferred_store_text))),
                                                    area_of_sheet(l.sheet_tl_name)) for l in g))
            where, reason = attribute_lead(
                store_shop=shop_key(sid) if sid else None, appointment_shop=shop_key(aid) if aid else None,
                remarks_shops=remarks, lead_area=next((area_of_sheet(l.sheet_tl_name) for l in g), None),
                target_shop=target_shop, target_area=target_area, area_shop_count=len(area_shops),
                sheet_shop=next((shop_of_sheet(l.sheet_tl_name) for l in g if shop_of_sheet(l.sheet_tl_name)), None),
            )
            if where == "store":
                mine.append(g)
                if count_how:
                    how[reason] += 1
            elif where == "area":
                pool.append(g)
        return mine, pool

    # leads that arrived in the period
    mine, pool = await split(await crm_metrics.leads_in_period(db, candidates, p_start, p_end), True)

    # sales made in the period, by leads that may have arrived earlier
    sold = await crm_metrics.leads_in_period(
        db, candidates, p_start - timedelta(days=CONVERSION_LOOKBACK_DAYS), p_end,
        extra=TeleCallLead.status == "Sale Conversion")
    sold_at = await _conversion_times(db, [l.id for l in sold])
    sold = [l for l in sold if p_start <= (sold_at.get(l.id) or arrived_at(l)) < p_end]
    mine_sold, pool_sold = await split(sold, False)

    own = _lead_figures(mine, mine_sold)
    kpis, by_status = own["kpis"], own["status_counts"]
    # Telecallers call every lead, so "outbound" is how many of them were called.
    called = kpis["total_leads"] - kpis["no_status"]
    telecalling = {"leads": kpis["total_leads"], "called": called, "not_called": kpis["no_status"],
                   "connected": kpis["calls_connected"], "not_connected": kpis["calls_not_connected"],
                   "connected_pct": kpis["connected_pct"]}

    visits = dict((await db.execute(
        select(TeleAppointment.attendance, func.count(TeleAppointment.id)).where(
            TeleAppointment.store_id.in_(same_shop_ids),
            TeleAppointment.scheduled_at >= p_start, TeleAppointment.scheduled_at < p_end,
        ).group_by(TeleAppointment.attendance)
    )).all())

    targets = _store_lead_target(await _lead_targets(db), store.id)
    volume = pace(targets["leads_monthly"], kpis["total_leads"], start, end, today)
    conv_monthly = targets["leads_monthly"] * targets["conversion_pct"] / 100
    conversions = pace(conv_monthly, kpis["converted"], start, end, today)
    ranked = [b for b in own["sources"] if b["leads"] >= 5]
    best = max(ranked, key=lambda b: b["rate"]) if ranked else None
    area_label = AREA_LABELS.get(target_area or "", "")
    area = None
    if pool:
        a = _lead_figures(pool, pool_sold)
        area = {"label": area_label, "shops": len(area_shops), "total": a["kpis"]["total_leads"],
                "converted": a["kpis"]["converted"], "status_counts": a["status_counts"], "sources": a["sources"]}
    return {
        "targets": targets,
        "total": kpis["total_leads"],
        "converted": kpis["converted"],
        "conversion_pct": kpis["conversion_pct"],
        "conversion_target_pct": targets["conversion_pct"],
        "revenue": round(kpis["total_sale_amount"], 2),
        "volume": volume.as_dict(),
        "conversions": conversions.as_dict(),
        "sources": own["sources"],
        "best_source": {"label": best["label"], "rate": best["rate"]} if best else None,
        "status_counts": by_status,
        "untouched": by_status.get(NO_STATUS, 0),
        "warm": sum(by_status.get(s, 0) for s in WARM_STATUSES),
        "visits": {"attended": visits.get("attended", 0), "scheduled": visits.get("scheduled", 0),
                   "no_show": visits.get("no_show", 0), "total": sum(visits.values())},
        "telecalling": telecalling,
        "lead_sheets": sorted({s.title() for s in area_sheets}),
        "matched_by": dict(how),
        "duplicates_merged": own["merged"],
        "area": area,
        "area_label": area_label,
    }


async def _same_shop_ids(db: AsyncSession, store: Store) -> list[int]:
    """This store and its duplicate records ("TVM" / "Kerala Trivandrum")."""
    shop = shop_of(store.name)
    if not shop:
        return [store.id]
    return [sid for sid, name in (await db.execute(select(Store.id, Store.name))).all() if shop_of(name) == shop]


async def _activity(db: AsyncSession, store_ids: list[int], start: date, end: date, sales: dict,
                    leads: dict, tracker_rows: list[DailyStoreTracker]) -> dict:
    """What happened at and around the store: walk-ins (Walk-ins sheet),
    store calls and inbound leads (the stores' daily form), bills (MCP),
    telecalling on its leads (CRM) and WhatsApp (Daily Tracker)."""
    walk = (await db.execute(select(StoreWalkin).where(
        StoreWalkin.store_id.in_(store_ids), StoreWalkin.date >= start, StoreWalkin.date <= end,
    ))).scalars().all()
    last_walk = (await db.execute(select(func.max(StoreWalkin.date)).where(
        StoreWalkin.store_id.in_(store_ids), StoreWalkin.date <= date.today()))).scalar()
    walkins = None
    if walk:
        actual = sum(w.actual or 0 for w in walk)
        dsr = sum(w.dsr or 0 for w in walk)
        # The visitor count when the store keeps one, else its DSR figure.
        counted = sum((w.actual if w.actual is not None else w.dsr) or 0 for w in walk)
        walkins = {"total": counted, "actual": actual, "dsr": dsr, "days_reported": len({w.date for w in walk}),
                   "has_actual": any(w.actual is not None for w in walk),
                   "bill_pct": round(sales["sales_count"] / counted * 100, 1) if counted else None}
    subs = (await db.execute(select(DailySubmission).where(
        DailySubmission.store_id.in_(store_ids), DailySubmission.date >= start, DailySubmission.date <= end,
    ))).scalars().all()
    last_ops = (await db.execute(
        select(func.max(DailySubmission.date)).where(DailySubmission.store_id.in_(store_ids),
                                                      DailySubmission.date <= date.today())
    )).scalar()
    ops = None
    if subs:
        tot = {k: sum(getattr(r, k) or 0 for r in subs)
               for k in ("walk_ins", "walk_in_conversions", "calls_made", "calls_connected", "new_leads",
                         "inbound_leads", "outbound_leads", "appointments_set", "home_deliveries")}
        lost: dict[str, int] = defaultdict(int)
        for r in subs:
            for reason, n in (r.lost_reasons or {}).items():
                lost[reason] += int(n or 0)
        ops = {**tot, "days_reported": len({r.date for r in subs}), "revenue": float(sum(r.revenue or 0 for r in subs)),
               "lost_reasons": dict(sorted(lost.items(), key=lambda kv: -kv[1])),
               "walk_in_conversion_pct": round(tot["walk_in_conversions"] / tot["walk_ins"] * 100, 1) if tot["walk_ins"] else None,
               "calls_connected_pct": round(tot["calls_connected"] / tot["calls_made"] * 100, 1) if tot["calls_made"] else None}
    return {
        "walkins": walkins,
        "walkins_last_date": last_walk.isoformat() if last_walk else None,
        "ops": ops,
        "ops_last_date": last_ops.isoformat() if last_ops else None,
        "bills": sales["sales_count"],
        "units": sales["units"],
        "telecalling": leads["telecalling"],
        "visits": leads["visits"],
        "whatsapp": {"chats": sum(r.wa_chats_received or 0 for r in tracker_rows),
                     "walkins_booked": sum(r.wa_walkins_booked or 0 for r in tracker_rows)} if tracker_rows else None,
    }


def _add_sheet_counts(leads: dict, activity: dict, start: date, end: date, today: date) -> None:
    """Walk-ins, inbound/outbound enquiries and WhatsApp chats aren't CRM
    leads: the stores count them in sheets. Their counts fill those rows of
    the source table (the larger of the CRM and sheet figure, as the CRM
    ones are a subset), and the totals and lead target follow."""
    ops, walk, wa = activity["ops"], activity["walkins"], activity["whatsapp"]
    sheet = {}  # key: (leads, converted or None, caption)
    if walk:
        sheet["walk_ins"] = (walk["total"], ops["walk_in_conversions"] if ops else None,
                             "Walk-ins sheet" + (" · bought: store daily form" if ops else ""))
    elif ops and ops["walk_ins"]:
        sheet["walk_ins"] = (ops["walk_ins"], ops["walk_in_conversions"], "Store daily form")
    if ops:
        sheet["inbound_calls"] = (ops["inbound_leads"], None, "Store daily form")
        sheet["outbound_calls"] = (ops["outbound_leads"], None, "Store daily form")
    if wa and wa["chats"]:
        sheet["whatsapp"] = (wa["chats"], None, "Daily Tracker (WhatsApp chats)")
    for b in leads["sources"]:
        if b["key"] not in sheet:
            continue
        n, conv, caption = sheet[b["key"]]
        if n > b["leads"]:
            b["leads"], b["from"] = n, caption
            if conv is not None and conv > b["converted"]:
                b["converted"] = conv
            b["converted_unknown"] = conv is None and not b["converted"]
            b["rate"] = round(b["converted"] / b["leads"] * 100, 1) if b["leads"] else 0.0
    total = sum(b["leads"] for b in leads["sources"])
    converted = sum(b["converted"] for b in leads["sources"])
    t = leads["targets"]
    leads.update({
        "total": total, "converted": converted,
        "conversion_pct": round(converted / total * 100, 1) if total else 0.0,
        "volume": pace(t["leads_monthly"], total, start, end, today).as_dict(),
        "conversions": pace(t["leads_monthly"] * t["conversion_pct"] / 100, converted, start, end, today).as_dict(),
    })


@router.get("/{store_id}")
async def store_portfolio(
    store_id: int,
    start: Optional[date] = None,
    end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_store(await allowed_store_ids(user, db), store_id)
    row = (await db.execute(
        select(Store, User.name).outerjoin(User, Store.team_leader_id == User.id).where(Store.id == store_id)
    )).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Store not found")
    store, tl_name = row

    # Default: the whole current month, measured as of today.
    today = date.today()
    if start is None:
        start = (end or today).replace(day=1)
    if end is None:
        end = start.replace(day=days_in_month(start))
    if start > end:
        raise HTTPException(status_code=400, detail="start must be on or before end")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Pick a range of at most {MAX_RANGE_DAYS} days")

    # Store.currency_code defaults to INR even abroad, so the country decides.
    currency = COUNTRY_CURRENCY.get(store.country or "") or store.currency_code or "INR"
    span_months = (end.year - start.year) * 12 + end.month - start.month + 1
    history = await _tracker_months(db, store.id, end, months=max(6, span_months))
    social = await _social(db, store, history, start, end, today)
    leads = await _leads(db, store, start, end, today)
    sales = await _sales(db, store, start, end, today)
    reviews = await _reviews(db, store, history, start, end)
    store_ids = await _same_shop_ids(db, store)
    activity = await _activity(db, store_ids, start, end, sales, leads, _in_range(history, start, end))
    _add_sheet_counts(leads, activity, start, end, today)
    analysis = analyse(social, leads, sales, reviews, _money_formatter(currency))
    sheet_updated = max((r.sheet_updated_at for r in history if r.sheet_updated_at), default=None)

    return {
        "store": {
            "id": store.id, "name": store.name, "country": store.country or "", "region": store.region or "",
            "address": store.address or "", "team_leader": tl_name or "", "is_active": bool(store.is_active),
            "currency": currency,
        },
        "period": {"start": start.isoformat(), "end": end.isoformat(), "as_of": min(today, end).isoformat(),
                   "days_total": sales["pace"]["days_total"], "days_remaining": sales["pace"]["days_remaining"]},
        "social": social,
        "leads": leads,
        "sales": sales,
        "reviews": reviews,
        "activity": activity,
        "analysis": analysis,
        "sheet_updated_at": sheet_updated.isoformat() + "Z" if sheet_updated else None,
    }
