"""Store performance portfolio — the pure maths behind /store-portfolio.

Everything here works on plain numbers so it can be tested without a
database: monthly targets pro-rated to any date range, pace against target,
lead-source grouping, and the rule-based "Overall Analysis & Action Plan".
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

# ── Lead sources ────────────────────────────────────────────────────
# The portfolio's sources, in display order, and which CRM source channels
# (crm.source_key) feed each. Outbound Calls has no channel yet. A city
# sheet row belongs where its "Lead Source" column says (PM / GM); with
# that cell blank it is Unknown source until someone fills it in.
LEAD_SOURCES: list[tuple[str, str, set[str]]] = [
    ("performance_marketing", "Performance Marketing", {"facebook", "instagram"}),
    ("growth_marketing", "Growth Marketing", {"referral", "app"}),
    ("whatsapp", "WhatsApp", {"whatsapp"}),
    ("website", "Website", {"website"}),
    ("inbound_calls", "Inbound Calls", {"phone"}),
    ("outbound_calls", "Outbound Calls", set()),
    ("walk_ins", "Walk-ins", {"walk_in"}),
    ("unknown", "Unknown source", {"meta_sheet"}),
]
_CHANNEL_TO_SOURCE = {ch: key for key, _label, chans in LEAD_SOURCES for ch in chans}
# The city sheets' own "Lead Source" column says PM / GM.
_TYPED_SOURCE = {"pm": "performance_marketing", "performance marketing": "performance_marketing",
                 "gm": "growth_marketing", "growth marketing": "growth_marketing"}


def lead_source_bucket(channel: str, typed: str = "") -> str:
    """Portfolio source for a lead: the sheet's PM/GM tag when present, else
    its CRM source channel. A sheet row with no (or an unrecognised) tag is
    Unknown source — read on every request, so it moves to PM/GM as soon as
    the sheet's cell is filled. Other unknown channels count as Growth
    Marketing (organic/other) so no lead is ever dropped."""
    tag = _TYPED_SOURCE.get(" ".join((typed or "").lower().split()))
    if tag:
        return tag
    return _CHANNEL_TO_SOURCE.get(channel, "growth_marketing")


# ── Which store a lead belongs to (read-time rules, nothing stored) ──
# The city sheets only say which area a lead is from; stores are named
# inconsistently ("TVM" / "Kerala Trivandrum"). These rules work it out
# without editing any sheet or record:
#   * every store has a "shop" (TVM and Kerala Trivandrum are one shop) and
#     an area; placeholders like "Kerala Store" have an area but no shop;
#   * every lead has an area from its city sheet;
#   * a lead belongs to a shop when it has a store or an appointment at a
#     store; else when its sheet is that shop's own sheet (Mysore); else,
#     when its area has only one shop (Guwahati), that shop;
#     else when its remarks name exactly one shop of its area (Meta's "city"
#     answer lands there too); otherwise it stays an area lead.
AREA_LABELS = {
    "kerala": "Kerala", "assam": "Assam", "karnataka": "Karnataka",
    "tamil_nadu": "Tamil Nadu", "north": "Delhi, Hyderabad & Mumbai",
}
SHEET_AREA = {"kerala": "kerala", "guwahati": "assam", "bangalore": "karnataka",
              "mysore": "karnataka", "mangalore": "karnataka",
              "chennai": "tamil_nadu", "delhi": "north"}
# Sheets that hold one shop's leads only, not a whole area's.
SHEET_SHOP = {"mysore": "mysore", "mangalore": "mangalore"}
# (shop, area, spellings) — most specific first, so "Delhi Lajpat Nagar"
# is Lajpat Nagar, not Delhi.
SHOPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("kochi", "kerala", ("kochi", "cochin", "ernakulam")),
    ("calicut", "kerala", ("calicut", "kozhikode")),
    ("kannur", "kerala", ("kannur",)),
    ("kasaragod", "kerala", ("kasaragod", "kasargod", "kasarkod", "kanhangad", "kanhagad", "kanjangad")),
    ("kollam", "kerala", ("kollam",)),
    ("kottakkal", "kerala", ("kottakkal", "kottkal", "kottakal")),
    ("palakkad", "kerala", ("palakkad", "palghat")),
    ("pathanamthitta", "kerala", ("pathanamthitta", "pathanamathitta", "pat")),
    ("thrissur", "kerala", ("thrissur", "trichur")),
    ("trivandrum", "kerala", ("trivandrum", "tvm", "thiruvananthapuram", "kazhakkoottam", "kazhakoottam",
                              "kazhakuttam")),
    ("wayanad", "kerala", ("wayanad",)),
    ("guwahati", "assam", ("guwahati",)),
    ("indiranagar", "karnataka", ("indiranagar", "indira nagar", "indranagar", "indra nagar")),
    ("marathahalli", "karnataka", ("marathahalli",)),
    ("mysore", "karnataka", ("mysore", "mysuru")),
    ("mangalore", "karnataka", ("mangalore", "mangaluru")),
    ("velachery", "tamil_nadu", ("velachery",)),
    ("kodambakkam", "tamil_nadu", ("kodambakkam", "kodambakam")),
    ("coimbatore", "tamil_nadu", ("coimbatore",)),
    ("lajpat_nagar", "north", ("lajpat nagar",)),
    ("hitech_city", "north", ("hitech city", "hi tech city", "hitec city", "hitech", "hitec")),
    ("kukatpally", "north", ("kukatpally",)),
    ("korum", "north", ("korum",)),
    ("bandra", "north", ("bandra",)),
    ("delhi", "north", ("delhi",)),
]
# Area words that alone don't name a shop ("Kerala Store" is a placeholder).
_AREA_WORDS = {
    "kerala": "kerala", "assam": "assam", "karnataka": "karnataka", "bangalore": "karnataka",
    "bengaluru": "karnataka", "tamil nadu": "tamil_nadu", "tn": "tamil_nadu", "chennai": "tamil_nadu",
    "delhi": "north", "hyderabad": "north", "telangana": "north", "mumbai": "north", "maharashtra": "north",
}
_SHOP_AREA = {shop: area for shop, area, _ in SHOPS}


def _words(text: str) -> str:
    return " " + " ".join("".join(c if c.isalnum() else " " for c in (text or "").lower()).split()) + " "


def _has(text: str, phrase: str) -> bool:
    return f" {phrase} " in text


def shop_of(name: str) -> Optional[str]:
    """The shop a store name stands for, or None for placeholders
    ("Kerala Store", "Delhi Store") and stores outside these areas."""
    w = _words(name)
    if _has(w, "store") and not any(_has(w, sp) for shop, _, sps in SHOPS if shop != "delhi" for sp in sps):
        return None  # "<area> Store" — a placeholder, not a shop
    for shop, _area, spellings in SHOPS:
        if any(_has(w, sp) for sp in spellings):
            return shop
    return None


def area_of_store(name: str, region: str = "") -> Optional[str]:
    shop = shop_of(name)
    if shop:
        return _SHOP_AREA[shop]
    for text in (name, region):
        w = _words(text)
        for word, area in _AREA_WORDS.items():
            if _has(w, word):
                return area
    return None


def area_of_sheet(sheet: str) -> Optional[str]:
    return SHEET_AREA.get((sheet or "").strip().lower())


def shop_of_sheet(sheet: str) -> Optional[str]:
    return SHEET_SHOP.get((sheet or "").strip().lower())


def shops_mentioned(text: str, area: Optional[str]) -> set[str]:
    """Shops of `area` named in free text (remarks, Meta's city answer).
    Area-wide words ("bangalore") don't count, and neither does "pat",
    which is too short to trust outside a store name."""
    w = _words(text)
    return {shop for shop, a, sps in SHOPS
            if (area is None or a == area) and shop != "delhi"
            and any(_has(w, sp) for sp in sps if sp != "pat")}


def attribute_lead(*, store_shop: Optional[str], appointment_shop: Optional[str], remarks_shops: set[str],
                   lead_area: Optional[str], target_shop: str, target_area: Optional[str],
                   area_shop_count: int, sheet_shop: Optional[str] = None) -> tuple[Optional[str], str]:
    """("store" | "area" | None, reason) for one lead and one target shop."""
    for shop, reason in ((store_shop, "store on the lead"), (appointment_shop, "appointment at the store"),
                         (sheet_shop, "the shop's own lead sheet")):
        if shop:
            return ("store" if shop == target_shop else None), reason
    if not lead_area or lead_area != target_area:
        return None, "other area"
    if area_shop_count == 1:
        return "store", "only shop in the area"
    if len(remarks_shops) == 1:
        return ("store" if target_shop in remarks_shops else None), "shop named in remarks"
    return "area", "shop not known"


DUPLICATE_WINDOW_DAYS = 7
STATUS_RANK = {"Sale Conversion": 6, "Appointment": 5, "Will Visit": 4, "Call back later": 3,
               "Not Interested": 2, "Call Not Connected": 1, "Unattended": 1, "Wrong number": 1}


def _phone_key(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


def group_duplicates(leads: list, when) -> list[list]:
    """The same person (same phone) arriving again within a week — from a
    sheet, Meta or the website — is one lead. `when(lead)` gives its time."""
    by_phone: dict[str, list] = {}
    groups: list[list] = []
    for lead in sorted(leads, key=when):
        key = _phone_key(lead.phone)
        if not key:
            groups.append([lead])
            continue
        last = by_phone.get(key)
        if last and (when(lead) - when(last[-1])).days <= DUPLICATE_WINDOW_DAYS:
            last.append(lead)
        else:
            by_phone[key] = [lead]
            groups.append(by_phone[key])
    return groups


def best_of(group: list):
    """The copy whose status is furthest along stands for the group."""
    return max(group, key=lambda l: STATUS_RANK.get(l.status or "", 0))


# Current lead status, in the stages a team leader works with.
STATUS_GROUPS = [
    ("new", "New", None), ("unattended", "Unattended", None),
    ("follow_up", "Follow-up", {"Call Not Connected", "Unattended", "Call back later"}),
    ("visit_planned", "Visit planned", {"Will Visit", "Appointment"}),
    ("converted", "Converted", {"Sale Conversion"}),
    ("lost", "Lost", {"Not Interested", "Wrong number"}),
]
NEW_LEAD_HOURS = 24


def status_groups(leads: list, when, now) -> list[dict]:
    """Each lead in one group by its call status; a lead nobody has called
    is New for its first day, then Unattended."""
    counts = {key: 0 for key, _l, _s in STATUS_GROUPS}
    for lead in leads:
        st = lead.status or ""
        if not st:
            counts["new" if (now - when(lead)).total_seconds() < NEW_LEAD_HOURS * 3600 else "unattended"] += 1
            continue
        for key, _label, statuses in STATUS_GROUPS:
            if statuses and st in statuses:
                counts[key] += 1
                break
    return [{"key": k, "label": label, "count": counts[k]} for k, label, _s in STATUS_GROUPS]


# ── Targets ────────────────────────────────────────────────────────
DEFAULT_LEAD_TARGETS = {"leads_monthly": 3000, "conversion_pct": 10.0}

# Same colour guide the Social Performance page uses.
VIEWS_GOOD_PCT, VIEWS_WARN_PCT = 90, 65
RATING_GOOD, RATING_WARN = 4.8, 4.5


def days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def prorated_target(monthly: float, start: date, end: date) -> float:
    """A monthly target spread evenly over each month's days, summed over
    [start, end] — 1M/month is 33,333/day in September, 32,258 in October."""
    if monthly <= 0 or end < start:
        return 0.0
    total, d = 0.0, start
    while d <= end:
        last = date(d.year, d.month, days_in_month(d))
        span_end = min(last, end)
        total += monthly * ((span_end - d).days + 1) / days_in_month(d)
        d = span_end + timedelta(days=1)
    return total


@dataclass
class Pace:
    target: float
    achieved: float
    expected_to_date: float
    days_total: int
    days_elapsed: int
    days_remaining: int

    @property
    def pct(self) -> Optional[float]:
        return round(self.achieved / self.target * 100, 1) if self.target > 0 else None

    @property
    def remaining(self) -> float:
        return max(self.target - self.achieved, 0.0)

    @property
    def required_daily(self) -> Optional[float]:
        if self.target <= 0 or self.remaining <= 0:
            return 0.0
        return self.remaining / self.days_remaining if self.days_remaining else None

    @property
    def current_daily(self) -> float:
        return self.achieved / self.days_elapsed if self.days_elapsed else 0.0

    @property
    def status(self) -> str:
        """achieved | ahead | on_track | behind | at_risk | no_target"""
        if self.target <= 0:
            return "no_target"
        if self.achieved >= self.target:
            return "achieved"
        if self.expected_to_date <= 0:
            return "on_track"
        ratio = self.achieved / self.expected_to_date
        if ratio >= 1:
            return "ahead"
        if ratio >= 0.9:
            return "on_track"
        return "behind" if ratio >= 0.75 else "at_risk"

    def as_dict(self) -> dict:
        return {
            "target": round(self.target, 2), "achieved": round(self.achieved, 2),
            "pct": self.pct, "remaining": round(self.remaining, 2),
            "expected_to_date": round(self.expected_to_date, 2),
            "days_total": self.days_total, "days_elapsed": self.days_elapsed,
            "days_remaining": self.days_remaining,
            "required_daily": None if self.required_daily is None else round(self.required_daily, 2),
            "current_daily": round(self.current_daily, 2),
            "status": self.status,
        }


def pace(monthly_target: float, achieved: float, start: date, end: date, today: date,
         as_of: Optional[date] = None) -> Pace:
    """Progress against a monthly target over [start, end] as of `today`.

    `as_of` is when the figures are counted up to, when that's earlier than
    today — a sheet's month-to-date row filled up to the 15th is judged
    against the target expected by the 15th, not by today."""
    elapsed_end = min(end, today, as_of) if as_of else min(end, today)
    days_total = (end - start).days + 1
    days_elapsed = max((elapsed_end - start).days + 1, 0)
    return Pace(
        target=prorated_target(monthly_target, start, end),
        achieved=achieved,
        expected_to_date=prorated_target(monthly_target, start, elapsed_end) if days_elapsed else 0.0,
        days_total=days_total,
        days_elapsed=days_elapsed,
        # days still to come for planning count from today, whatever the as-of date
        days_remaining=days_total - max((min(end, today) - start).days + 1, 0),
    )


# ── Overall analysis & action plan ─────────────────────────────────
PRIORITY = {"at_risk": "High", "behind": "Medium", "on_track": "Low",
            "ahead": "On track", "achieved": "Done", "no_target": "Set target", "no_data": "No data"}


def _n(x: float) -> str:
    return f"{round(x):,}"


def _per_day(p: dict) -> str:
    if p["required_daily"] is None:
        return "period ended"
    return f"{_n(p['required_daily'])}/day"


def analyse(social: dict, leads: dict, sales: dict, reviews: dict, money, stay: Optional[dict] = None) -> dict:
    """Rule-based read of the four sections: one row per area with the gap,
    the pace needed and the next step, plus strengths and concerns.
    `money` formats an amount in the store's currency."""
    rows: list[dict] = []
    strengths: list[str] = []
    concerns: list[str] = []

    # Social
    v = social.get("views")
    if not social.get("has_data"):
        last = social.get("last_report")
        gap = "Not reported in the tracker sheet for this period"
        if last and last.get("instagram_pct") is not None:
            gap += f" · last report {last['as_of']}: {_n(last['instagram'])} views ({last['instagram_pct']}% of target)"
        rows.append({"area": "social", "status": "no_data", "gap": gap,
                     "action": "Ask the store to update its month-to-date row in the Daily Tracker sheet (Instagram section)."})
        concerns.append("Social media not reported yet for this period")
    elif v:
        st = v["status"]
        gap = (f"{_n(v['remaining'])} views left · {_per_day(v)}" if v["remaining"] > 0
               else f"Target reached ({v['pct']}%)")
        if st in ("behind", "at_risk"):
            extra = (v["required_daily"] or 0) - v["current_daily"]
            reels = social.get("reels", 0)
            per_reel = social["views"]["achieved"] / reels if reels else 0
            more_reels = f" ≈ {max(1, round(extra * max(v['days_remaining'], 1) / per_reel))} more reels at the current {_n(per_reel)} views/reel" if per_reel and extra > 0 else ""
            action = (f"Add {_n(max(extra, 0))} views/day above the current {_n(v['current_daily'])}/day average{more_reels}; "
                      "review the top reels and boost distribution.")
            concerns.append(f"Social views at {v['pct']}% of target")
        else:
            action = "Keep the posting rhythm; reuse formats of the best-performing reels."
            strengths.append(f"Social views on pace ({v['pct']}% of target)")
        rows.append({"area": "social", "status": st, "gap": gap, "action": action})

    # Leads & conversion
    lv, cv = leads.get("volume"), leads.get("conversions")
    if lv and cv:
        worst = lv["status"] if _rank(lv["status"]) >= _rank(cv["status"]) else cv["status"]
        gap = (f"{_n(lv['remaining'])} leads left · {_per_day(lv)}; "
               f"{_n(cv['remaining'])} more conversions to reach {_n(cv['target'])}")
        steps = []
        untouched = leads.get("untouched", 0)
        if untouched:
            steps.append(f"Call the {_n(untouched)} leads with no status yet")
        warm = leads.get("warm", 0)
        if cv["remaining"] > 0 and warm:
            steps.append(f"follow up the {_n(warm)} Will Visit / Appointment / Call-back leads to convert {_n(min(cv['remaining'], warm))}")
        pool = leads.get("area")
        if pool and pool.get("total"):
            steps.append(f"{_n(pool['total'])} {pool['label']} leads have no shop yet — booking their store visit links them here")
        best = leads.get("best_source")
        if lv["status"] in ("behind", "at_risk") and best:
            steps.append(f"shift budget toward {best['label']} ({best['rate']}% conversion)")
        action = ("; ".join(steps) + ".") if steps else "Keep follow-up discipline; conversion is on pace."
        action = action[0].upper() + action[1:]
        rows.append({"area": "leads", "status": worst, "gap": gap, "action": action})
        if lv["status"] in ("behind", "at_risk"):
            concerns.append(f"Lead volume at {lv['pct']}% of target")
        else:
            strengths.append(f"Lead volume on pace ({lv['pct']}% of target)")
        rate, rate_target = leads.get("conversion_pct", 0), leads.get("conversion_target_pct", 0)
        if rate_target and rate < rate_target:
            concerns.append(f"Conversion {rate}% vs {rate_target}% target")
        elif rate_target:
            strengths.append(f"Conversion {rate}% meets the {rate_target}% target")

    # Hot leads and customers (from the stay-on-target funnel)
    for st in (stay or {}).get("stages", [])[2:]:
        p = st["pace"]
        if not p:
            continue
        tgt = f"{_n(p['target'])} target" + (" (proposed)" if st["proposed"] else "")
        if p["remaining"] > 0:
            gap = f"{_n(p['remaining'])} more {st['unit']} for the {tgt} · {_per_day(p)}"
        else:
            gap = f"Target reached ({p['pct']}%)"
        action = ("Offer the ₹99 advance on interested calls; mark leads Hot when they pay or agree." if st["key"] == "hot"
                  else "Follow up booked visits and walk-ins who didn't buy.")
        rows.append({"area": st["key"], "status": p["status"], "gap": gap, "action": action})
        if p["status"] in BEHIND:
            concerns.append(f"{st['title']} at {p['pct']}% of target")

    # Sales
    s = sales.get("pace")
    if s and s["status"] != "no_target":
        bill = sales.get("avg_bill") or 0
        if s["remaining"] > 0:
            n_sales = f" · approx. {_n(s['remaining'] / bill)} sales" if bill else ""
            gap = f"{money(s['remaining'])} left · {money(s['required_daily']) + '/day' if s['required_daily'] is not None else 'period ended'}{n_sales}"
        else:
            gap = f"Target reached ({s['pct']}%)"
        if s["status"] in ("behind", "at_risk"):
            per_day_sales = f" (~{_n((s['required_daily'] or 0) / bill)} sales/day at {money(bill)} average bill)" if bill else ""
            action = f"Need {money(s['required_daily'] or 0)}/day{per_day_sales}; prioritise ready-to-buy leads and upsell plans."
            concerns.append(f"Sales at {s['pct']}% of target")
        else:
            action = "On pace — keep converting walk-ins and booked visits." if s["remaining"] > 0 else "Target met — push for stretch revenue."
            strengths.append(f"Sales {'ahead of pace' if s['status'] == 'ahead' else 'on track'} ({s['pct']}% of target)")
        rows.append({"area": "sales", "status": s["status"], "gap": gap, "action": action})
    else:
        rows.append({"area": "sales", "status": "no_target", "gap": "No MCP sales target for this store",
                     "action": "Set the store's monthly target in MCP so pace can be tracked."})

    # Google reviews
    rating = reviews.get("rating")
    if rating is None:
        rows.append({"area": "reviews", "status": "no_data", "gap": "No Google rating reported",
                     "action": "Fill the Google rating column in the Daily Tracker sheet."})
    else:
        st = "ahead" if rating >= RATING_GOOD else "behind" if rating >= RATING_WARN else "at_risk"
        negatives, unanswered = reviews.get("negative"), reviews.get("unanswered")
        steps = []
        if unanswered:
            steps.append(f"reply to {_n(unanswered)} unanswered reviews")
        elif negatives:
            steps.append(f"respond to the {_n(negatives)} negative reviews and fix the issues raised")
        if reviews.get("response", "") in ("No", "Partial"):
            steps.append("reply to every review, not just some")
        if rating < RATING_GOOD:
            steps.append(f"ask happy customers for a review to lift the {rating:.1f}★ rating toward {RATING_GOOD}")
        if not reviews.get("new_reviews"):
            steps.append("no new reviews this period — add a review request at billing")
        if negatives and st == "ahead":
            st = "on_track"
        gap = f"{rating:.1f}★ · {_n(reviews.get('new_reviews') or 0)} new reviews"
        if negatives is not None:
            gap += f" · {_n(negatives)} negative"
        action = ("; ".join(steps) + ".") if steps else "Rating is strong — keep replying to every review."
        action = action[0].upper() + action[1:]
        rows.append({"area": "reviews", "status": st, "gap": gap, "action": action})
        (strengths if st in ("ahead", "on_track") else concerns).append(f"Google rating {rating:.1f}★")

    for r in rows:
        r["priority"] = PRIORITY.get(r["status"], "Low")
    behind = [r["area"] for r in rows if r["status"] in ("behind", "at_risk")]
    return {"rows": rows, "strengths": strengths, "concerns": concerns, "needs_attention": behind}


_RANKS = {"no_target": 0, "no_data": 0, "achieved": 1, "ahead": 1, "on_track": 2, "behind": 3, "at_risk": 4}


def _rank(status: str) -> int:
    return _RANKS.get(status, 0)


# ── "What should you do now to stay on target?" ─────────────────────
# The store's funnel — Visibility → Leads → Hot leads → Customers — with a
# target and pace for each stage, where it's slipping, and the next steps.
# Targets the app has no setting for yet are derived and flagged "proposed":
#   customers = monthly sales target ÷ average bill;
#   hot leads = customers ÷ a 40% (min) to 30% (stretch) hot-to-customer rate;
#   leads stretch = LEAD_STRETCH_MONTHLY.
LEAD_STRETCH_MONTHLY = 5000
HOT_CLOSE_RATE = (0.40, 0.30)  # (min target, stretch target)
_STAGE_UNITS = {"visibility": "views", "leads": "leads", "hot": "hot leads", "customers": "customers"}
_NEXT_STEP = {
    "visibility": "Post more reels; reuse the formats that got the most views.",
    "leads": "Keep campaigns running; log every inbound call and walk-in enquiry.",
    "hot": "Offer the ₹99 advance to interested leads; mark them Hot when they pay or agree.",
    "customers": "Follow up every booked visit; ask walk-ins who don't buy why.",
}
BEHIND = ("behind", "at_risk")


def _ratio(p: Pace) -> float:
    return p.achieved / p.expected_to_date if p.expected_to_date else 1.0


def _stage(key: str, title: str, value: Optional[float], monthly: float, start: date, end: date, today: date,
           *, stretch: float = 0, as_of: Optional[date] = None, proposed: bool = False,
           quality: str = "good", source: str = "", not_recorded: bool = False) -> dict:
    p = pace(monthly, value or 0, start, end, today, as_of=as_of) if value is not None and monthly else None
    top = pace(stretch, value or 0, start, end, today, as_of=as_of) if p and stretch else None
    return {
        "key": key, "title": title, "unit": _STAGE_UNITS[key], "value": value, "not_recorded": not_recorded,
        "target_monthly": monthly or None, "stretch_monthly": stretch or None, "proposed": proposed,
        "pace": p.as_dict() if p else None, "ratio": round(_ratio(p), 3) if p else None,
        "stretch_pace": top.as_dict() if top else None,
        "status": (p.status if p else "no_data"), "quality": quality, "source": source,
    }


def funnel(*, start: date, end: date, today: date, social: dict, leads: dict, sales: dict, reviews: dict,
           walkins: Optional[dict], team_leader: str, money) -> dict:
    """Plain numbers in, the stay-on-target section out (no database)."""
    closed = sales["pace"]["days_remaining"] == 0
    days_total = sales["pace"]["days_total"]

    # 1. Visibility: the tracker's month-to-date Instagram views
    vis = social["views"]
    as_of = date.fromisoformat(social["as_of"]) if social.get("as_of") else None
    last = social.get("last_report")
    visibility = _stage(
        "visibility", "Visibility", vis["achieved"] if social.get("has_data") else None, vis["monthly_target"],
        start, end, today, as_of=as_of,
        quality="good" if social.get("has_data") else "bad",
        source=(f"Daily Tracker sheet, Instagram up to {social['as_of']}" if social.get("has_data")
                else f"Not reported for this period · last report {last['as_of']}: {_n(last['instagram'])} views" if last
                else "Not reported in the Daily Tracker sheet"))
    visibility["followers"] = {"total": social.get("followers") or 0, "new": social.get("new_followers") or 0}

    # 2. Lead generation: every channel the store records
    bills = sales["sales_count"]
    total = leads["total"]
    pool = leads.get("area") or {}
    lead_stage = _stage(
        "leads", "Lead generation", total if total else None, leads["targets"]["leads_monthly"], start, end, today,
        stretch=LEAD_STRETCH_MONTHLY, not_recorded=not total,
        quality="bad" if not total else "warn" if pool.get("total") else "good",
        source=(f"Not recorded: {_n(bills)} people bought, so leads came in, but no source logged them" if not total
                else f"{_n(pool['total'])} {pool.get('label', '')} area leads can't be linked to a shop and aren't counted"
                if pool.get("total") else "All its lead sources are counted"))

    # 3. Hot leads: website leads (₹99 paid) + leads marked Hot
    avg_bill = sales.get("avg_bill") or 0
    cust_monthly = round(sales["monthly_target"] / avg_bill) if avg_bill and sales["monthly_target"] else 0
    hot = leads.get("hot") or {"total": 0, "website": 0, "marked": 0}
    hot_stage = _stage(
        "hot", "Hot leads", hot["total"], round(cust_monthly / HOT_CLOSE_RATE[0]) if cust_monthly else 0,
        start, end, today, stretch=round(cust_monthly / HOT_CLOSE_RATE[1]) if cust_monthly else 0, proposed=True,
        quality="warn", source=f"{_n(hot['website'])} website (₹99 paid) · {_n(hot['marked'])} marked Hot")
    hot_stage["breakdown"] = hot

    # 4. Customers: MCP bills
    cust_stage = _stage("customers", "Customers", bills, cust_monthly, start, end, today, proposed=True,
                        source=f"MCP bills · {money(sales['pace']['achieved'])} revenue")
    stages = [visibility, lead_stage, hot_stage, cust_stage]

    def rate(a, b):
        return round(a / b * 100, 1) if a is not None and b else None
    v, l_, h, c = (s["value"] for s in stages)
    ratios = [{"label": "Views → leads", "pct": rate(l_, v)}, {"label": "Leads → hot leads", "pct": rate(h, l_)},
              {"label": "Hot leads → customers", "pct": rate(c, h)}, {"label": "Leads → customers", "pct": rate(c, l_)}]

    # Where it's slipping: one row per stage
    slipping = []
    for s in stages:
        p, top = s["pace"], s["stretch_pace"]
        row = {"key": s["key"], "title": s["title"], "status": s["status"], "next_step": _NEXT_STEP[s["key"]]}
        if not p:
            row.update(kind="not_measured", note=s["source"])
        elif p["achieved"] >= p["target"]:
            row.update(kind="reached", achieved=p["achieved"], target=p["target"])
        elif closed:
            row.update(kind="short", short=p["remaining"], pct=p["pct"])
        else:
            row.update(kind="pace", behind=round(p["expected_to_date"] - p["achieved"], 1),
                       need_more=p["remaining"], need_more_stretch=top["remaining"] if top else None,
                       per_day_needed=p["required_daily"], per_day_stretch=top["required_daily"] if top else None,
                       per_day_now=p["current_daily"])
        slipping.append(row)
    worst = sorted([s for s in stages if s["pace"] and s["pace"]["achieved"] < s["pace"]["target"]
                    and (closed or s["status"] in BEHIND)], key=lambda s: s["ratio"])[:2]

    # Run-rate: month-end at today's pace (open periods only)
    run_rate = None
    if not closed:
        elapsed = sales["pace"]["days_elapsed"]
        run_rate = {s["key"]: (round(s["value"] / elapsed * days_total) if s["value"] is not None and elapsed else None)
                    for s in stages}
        run_rate["revenue"] = round(sales["pace"]["achieved"] / elapsed * days_total) if elapsed else None

    return {
        "closed": closed, "stages": stages, "ratios": ratios, "slipping": slipping,
        "bottleneck": [{"key": s["key"], "title": s["title"], "pct": s["pace"]["pct"]} for s in worst],
        "not_measured": [s["title"] for s in stages if not s["pace"]],
        "run_rate": run_rate,
        "actions": _actions(stages, closed=closed, sales=sales, leads=leads, walkins=walkins, social=social,
                            reviews=reviews, team_leader=team_leader, money=money),
    }


def _actions(stages: list[dict], *, closed: bool, sales: dict, leads: dict, walkins: Optional[dict], social: dict,
             reviews: dict, team_leader: str, money) -> list[dict]:
    """Up to five next steps, most urgent first: (rank, who, text). Text may
    carry **bold** spans for the figures to act on."""
    vis, lead, hot, cust = stages
    tl = f"Team leader {team_leader}" if team_leader else "Team leader"
    out: list[tuple[float, str, str]] = []
    cp = cust["pace"]
    if cp and cp["achieved"] < cp["target"]:
        bill = sales.get("avg_bill") or 0
        if closed:
            out.append((_stage_rank(cust), f"{tl} · store team",
                        f"Closed at {_n(cp['achieved'])} of {_n(cp['target'])} customers ({money(sales['pace']['achieved'])}). "
                        f"Plan next month for {_n(cust['target_monthly'])} bills, about {cust['target_monthly'] / 30:.1f} a day."))
        elif cp["required_daily"] is not None and cp["status"] in BEHIND:
            per = cp["required_daily"]
            out.append((_stage_rank(cust), f"{tl} · store team",
                        f"Close **{per:.1f} sales a day** for the next {cp['days_remaining']} days "
                        f"(now {cp['current_daily']:.1f}/day)" + (f": {money(per * bill)} a day at a {money(bill)} average bill." if bill else ".")))
    if walkins and walkins.get("total"):
        bought = walkins.get("bills_same_days", sales["sales_count"])  # bills on the days the walk-ins were counted
        rate = round(bought / walkins["total"] * 100, 1)
        if bought and rate < 60:
            out.append((0.8, "Store team", f"Only **{rate}% of walk-ins bought** ({_n(bought)} bills from "
                                            f"{_n(walkins['total'])} walk-ins). Ask every walk-in who leaves without buying why, and note it in the daily form."))
        elif rate > 100:
            out.append((0.4, "Store team", f"**More bills ({_n(bought)}) than walk-ins counted ({_n(walkins['total'])})** on the same days: "
                                            "walk-ins are being under-counted. Count every visitor in the Walk-ins sheet."))
    hp = hot["pace"]
    if hp and hp["achieved"] < hp["target"]:
        warm = leads.get("warm", 0)
        out.append((0.05 if not hot["value"] else _stage_rank(hot), "Telecallers · TL",
                    ("**No hot leads yet.** Offer the ₹99 advance on every interested call and mark the lead Hot when the customer pays or agrees"
                     + (f" (start with the {_n(warm)} Will Visit / Call-back leads)." if warm else "."))
                    if not hot["value"] else
                    f"Need **{hp['required_daily'] or 0:.1f} more hot leads a day** (now {hp['current_daily']:.1f}/day): push the ₹99 advance on interested calls."))
    lp = lead["pace"]
    if lead["not_recorded"]:
        out.append((0, f"{tl} · store team", f"**Record this store's leads.** It made {_n(sales['sales_count'])} sales but no enquiry was logged: "
                                            "fill the daily form every evening (inbound leads, walk-ins) and its column in the Walk-ins sheet."))
    elif lp and lp["achieved"] < lp["target"] and (closed or lp["status"] in BEHIND):
        best = max((r for r in leads["sources"] if r["leads"]), key=lambda r: r["leads"], default=None)
        where = f" Most come from {best['label'].lower()} ({_n(best['leads'])})." if best else ""
        out.append((_stage_rank(lead), f"{tl} · marketing",
                    f"Leads finished at {_n(lp['achieved'])} of {_n(lp['target'])}.{where}" if closed else
                    f"Bring in **{lp['required_daily'] or 0:.0f} leads a day** (now {lp['current_daily']:.0f}/day).{where}"))
    vp = vis["pace"]
    if not vp:
        out.append((0.3, "Store team", "Fill this month's row in the Daily Tracker sheet (Instagram views and reels). Visibility can't be tracked without it."))
    elif vp["achieved"] < vp["target"] and (closed or vp["status"] in BEHIND):
        reels = social.get("reels") or 0
        per_reel = vp["achieved"] / reels if reels else 0
        more = f": about **{max(1, round(vp['remaining'] / per_reel))} more reels** at the current {_n(per_reel)} views per reel" if per_reel else ""
        out.append((_stage_rank(vis), "Store team · social", f"Need {_n(vp['remaining'])} more views{more}."))
    rating = reviews.get("rating")
    if rating is not None and rating < RATING_GOOD:
        out.append((0.6 + (rating - 4) / 10, "Store team",
                    f"Lift the Google rating from **{rating:.1f}★** toward {RATING_GOOD}★: ask happy customers for a review at billing"
                    + (f" and reply to the {_n(reviews['unanswered'])} unanswered reviews." if reviews.get("unanswered") else ".")))
    out.sort(key=lambda a: a[0])
    return [{"who": who, "text": text} for _, who, text in out[:5]]


def _stage_rank(stage: dict) -> float:
    return stage["ratio"] if stage.get("ratio") is not None else 0.5
