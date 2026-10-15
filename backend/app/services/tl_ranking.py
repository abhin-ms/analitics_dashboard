"""Team leader ranking: one performance score per team leader for a period,
built from four areas, each scored out of 100 against its target for the
days so far.

  Sales           40%  each store's MCP revenue against its prorated target
                       (averaged per store, so stores in different
                       currencies are never added together)
  Telecalling     25%  leads called (older than 24 h), calls connected,
                       follow-ups done on time — the average of whichever
                       of the three has data
  Lead generation 20%  new leads (duplicates by phone counted once) against
                       the lead target of the team leader's sheet tabs
  Conversion      15%  leads converted against the conversion target, and
                       walk-ins that bought against WALKIN_BUY_TARGET_PCT

An area with no data is left out and the other weights are scaled up, so
a missing data source neither drags a team leader down nor lifts them.
Pure functions only; the endpoint gathers the inputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .store_portfolio import days_in_month

AREAS: list[tuple[str, str, float]] = [
    ("sales", "Sales", 0.40),
    ("tele", "Telecalling", 0.25),
    ("leads", "Lead generation", 0.20),
    ("conv", "Conversion", 0.15),
]
WEIGHTS = {key: w for key, _label, w in AREAS}
# Share of walk-ins that should leave with a bill.
WALKIN_BUY_TARGET_PCT = 60.0
RATINGS = [(85, "Excellent"), (72, "Good"), (60, "Average"), (45, "Needs work"), (0, "Poor")]


def capped(value: Optional[float]) -> Optional[float]:
    return None if value is None else max(0.0, min(100.0, value))


def mean(values: list[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def pct(part: float, whole: float) -> Optional[float]:
    return part / whole * 100 if whole else None


def sales_score(stores: list[dict]) -> Optional[float]:
    """Average of each store's achievement (capped at 100); stores without a
    target don't count."""
    return mean([capped(pct(s["revenue"], s["target"])) for s in stores if s["target"] > 0])


def leads_score(unique_leads: int, target: float) -> Optional[float]:
    return capped(pct(unique_leads, target)) if target > 0 else None


def tele_score(called_pct: Optional[float], connected_pct: Optional[float],
               followups_pct: Optional[float]) -> Optional[float]:
    return mean([capped(called_pct), capped(connected_pct), capped(followups_pct)])


def conv_score(lead_conv_pct: Optional[float], conv_target_pct: float,
               walkin_buy_pct: Optional[float]) -> Optional[float]:
    lead_part = capped(lead_conv_pct / conv_target_pct * 100) if lead_conv_pct is not None and conv_target_pct > 0 else None
    walk_part = capped(walkin_buy_pct / WALKIN_BUY_TARGET_PCT * 100) if walkin_buy_pct is not None else None
    return mean([lead_part, walk_part])


def overall(areas: dict[str, Optional[float]]) -> Optional[float]:
    """Weighted score over the areas that have data."""
    have = {k: v for k, v in areas.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in have)
    if not total_w:
        return None
    return round(sum(v * WEIGHTS[k] for k, v in have.items()) / total_w, 1)


def rating(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    return next(label for floor, label in RATINGS if score >= floor)


def weakest(areas: dict[str, Optional[float]]) -> Optional[str]:
    have = {k: v for k, v in areas.items() if v is not None}
    # ties go to the heavier area: improving it moves the score most
    return min(have, key=lambda k: (have[k], -WEIGHTS[k])) if have else None


def previous_window(start: date, end: date) -> tuple[date, date, str]:
    """What a period is compared with: month-to-date against the same days
    of last month, anything else against the same number of days before."""
    if start.day == 1 and (start.year, start.month) == (end.year, end.month):
        prev_end_month = start - timedelta(days=1)
        prev_start = prev_end_month.replace(day=1)
        prev_end = prev_start.replace(day=min(end.day, days_in_month(prev_start)))
        return prev_start, prev_end, "same days last month"
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1), f"previous {length} day{'s' if length > 1 else ''}"


@dataclass
class Entry:
    team_leader_id: int
    name: str
    areas: dict[str, Optional[float]]
    details: dict = field(default_factory=dict)
    stores: list[str] = field(default_factory=list)
    previous_score: Optional[float] = None

    @property
    def score(self) -> Optional[float]:
        return overall(self.areas)


def rank(entries: list[Entry]) -> list[dict]:
    """Best first; team leaders with no data at all go last, unranked."""
    ordered = sorted(entries, key=lambda e: (e.score is None, -(e.score or 0), e.name.lower()))
    rows, position = [], 0
    for e in ordered:
        score = e.score
        if score is not None:
            position += 1
        rows.append({
            "team_leader_id": e.team_leader_id,
            "name": e.name,
            "stores": e.stores,
            "rank": position if score is not None else None,
            "score": score,
            "rating": rating(score),
            "previous_score": e.previous_score,
            "change": round(score - e.previous_score, 1) if score is not None and e.previous_score is not None else None,
            "areas": {k: (round(v, 1) if v is not None else None) for k, v in e.areas.items()},
            "weakest": weakest(e.areas),
            "details": e.details,
        })
    return rows


def team_average(rows: list[dict]) -> dict:
    return {
        "score": (round(m, 1) if (m := mean([r["score"] for r in rows])) is not None else None),
        "areas": {k: (round(m, 1) if (m := mean([r["areas"][k] for r in rows])) is not None else None)
                  for k, _l, _w in AREAS},
    }
