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
# The portfolio's seven sources, in display order, and which CRM source
# channels (crm.source_key) feed each. Outbound Calls has no channel yet.
LEAD_SOURCES: list[tuple[str, str, set[str]]] = [
    ("performance_marketing", "Performance Marketing", {"meta_sheet", "facebook", "instagram"}),
    ("growth_marketing", "Growth Marketing", {"referral", "app"}),
    ("whatsapp", "WhatsApp", {"whatsapp"}),
    ("website", "Website", {"website"}),
    ("inbound_calls", "Inbound Calls", {"phone"}),
    ("outbound_calls", "Outbound Calls", set()),
    ("walk_ins", "Walk-ins", {"walk_in"}),
]
_CHANNEL_TO_SOURCE = {ch: key for key, _label, chans in LEAD_SOURCES for ch in chans}
# The city sheets' own "Lead Source" column already says PM / GM.
_TYPED_SOURCE = {"pm": "performance_marketing", "performance marketing": "performance_marketing",
                 "gm": "growth_marketing", "growth marketing": "growth_marketing"}


def lead_source_bucket(channel: str, typed: str = "") -> str:
    """Portfolio source for a lead: the sheet's PM/GM tag when present, else
    its CRM source channel; unknown channels count as Growth Marketing
    (organic/other) so no lead is ever dropped."""
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


def analyse(social: dict, leads: dict, sales: dict, reviews: dict, money) -> dict:
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
