"""Time helpers for the telecalling CRM.

Storage convention (same as the rest of the app): naive UTC datetimes.
Business rules (working hours, "today", sheet dates) are in IST.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_WORKING_HOURS = {"start": "09:00", "end": "18:00", "days": [0, 1, 2, 3, 4, 5]}  # Mon–Sat


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_ist(dt_utc: datetime) -> datetime:
    """naive UTC -> aware IST"""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(IST)


def from_ist(dt_ist: datetime) -> datetime:
    """aware or naive IST -> naive UTC"""
    if dt_ist.tzinfo is None:
        dt_ist = dt_ist.replace(tzinfo=IST)
    return dt_ist.astimezone(timezone.utc).replace(tzinfo=None)


def ist_today(now_utc: datetime | None = None) -> date:
    return to_ist(now_utc or utcnow()).date()


def ist_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """[start, end) of an IST calendar day, as naive UTC."""
    start = from_ist(datetime.combine(day, time(0, 0)))
    return start, start + timedelta(days=1)


def iso_utc(dt: datetime | None) -> str | None:
    """Serialize a naive-UTC datetime so browsers parse it as UTC."""
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


def parse_client_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime sent by the frontend. Offset-aware values are
    converted to UTC; naive values are treated as IST (what the user saw)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return parse_sheet_datetime(value)
    if dt.tzinfo is None:
        return from_ist(dt)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


# ── Sheet date parsing ─────────────────────────────────────────────
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap]\.?m\.?)?", re.I)


def _parse_time_part(text: str) -> tuple[int, int, int] | None:
    m = _TIME_RE.search(text)
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    ampm = (m.group(4) or "").lower().replace(".", "")
    if ampm == "pm" and h < 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59 or s > 59:
        return None
    return h, mi, s


def parse_sheet_datetime(text: str | None) -> datetime | None:
    """Best-effort parse of a date/time typed or exported into the sheet.

    Handles ISO 8601 (with or without offset, e.g. Meta's
    "2026-09-24T10:00:00+05:30"), "2026-09-24 10:00", DD/MM/YYYY and
    DD-MM-YYYY (Indian order; MM/DD only when the day part is > 12),
    "24 Sep 2026", "Sep 24, 2026", each with an optional time. Values without
    an offset are IST. Returns naive UTC, or None if it can't be read.
    """
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    # ISO 8601
    iso = raw.replace("Z", "+00:00")
    if re.match(r"^\d{4}-\d{2}-\d{2}", iso):
        candidate = iso.replace(" ", "T", 1) if re.match(r"^\d{4}-\d{2}-\d{2} \d", iso) else iso
        # "+0530" -> "+05:30"
        candidate = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", candidate)
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                return from_ist(dt)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass

    tpart = _parse_time_part(raw)
    h, mi, s = tpart if tpart else (0, 0, 0)

    # D/M/Y or M/D/Y with / - or .
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", raw)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        day, month = a, b
        if b > 12 and a <= 12:  # clearly M/D/Y
            day, month = b, a
        try:
            return from_ist(datetime(y, month, day, h, mi, s))
        except ValueError:
            return None

    # "24 Sep 2026" / "24-Sep-2026"
    m = re.match(r"^(\d{1,2})[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{4})", raw)
    if m:
        month = _MONTHS.get(m.group(2)[:3].lower())
        if month:
            try:
                return from_ist(datetime(int(m.group(3)), month, int(m.group(1)), h, mi, s))
            except ValueError:
                return None

    # "Sep 24, 2026"
    m = re.match(r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        month = _MONTHS.get(m.group(1)[:3].lower())
        if month:
            try:
                return from_ist(datetime(int(m.group(3)), month, int(m.group(2)), h, mi, s))
            except ValueError:
                return None

    return None


# ── Working hours ──────────────────────────────────────────────────
def _hm(value: str, fallback: str) -> time:
    try:
        hh, mm = (value or fallback).split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        hh, mm = fallback.split(":")
        return time(int(hh), int(mm))


def _window_for_day(day: date, cfg: dict) -> tuple[datetime, datetime] | None:
    """Working window of an IST day as naive-UTC [start, end), or None."""
    days = cfg.get("days", DEFAULT_WORKING_HOURS["days"])
    if day.weekday() not in days:
        return None
    start = _hm(cfg.get("start"), DEFAULT_WORKING_HOURS["start"])
    end = _hm(cfg.get("end"), DEFAULT_WORKING_HOURS["end"])
    if end <= start:
        return None
    return from_ist(datetime.combine(day, start)), from_ist(datetime.combine(day, end))


def is_working_time(now_utc: datetime, cfg: dict) -> bool:
    w = _window_for_day(to_ist(now_utc).date(), cfg)
    return bool(w and w[0] <= now_utc < w[1])


def next_opening(from_utc: datetime, cfg: dict) -> datetime:
    """The earliest working instant >= from_utc."""
    day = to_ist(from_utc).date()
    for _ in range(15):
        w = _window_for_day(day, cfg)
        if w:
            if from_utc < w[0]:
                return w[0]
            if from_utc < w[1]:
                return from_utc
        day += timedelta(days=1)
    return from_utc  # no working days configured — behave like 24/7


def next_working_day_opening(from_utc: datetime, cfg: dict) -> datetime:
    """Opening time of the next working day strictly after from_utc's IST day."""
    day = to_ist(from_utc).date() + timedelta(days=1)
    for _ in range(15):
        w = _window_for_day(day, cfg)
        if w:
            return w[0]
        day += timedelta(days=1)
    return from_utc + timedelta(days=1)


def add_working_minutes(start_utc: datetime, minutes: float, cfg: dict) -> datetime:
    """start + N minutes counted only inside working hours."""
    remaining = timedelta(minutes=minutes)
    cursor = next_opening(start_utc, cfg)
    for _ in range(60):
        w = _window_for_day(to_ist(cursor).date(), cfg)
        if not w:
            # no working days configured at all
            return cursor + remaining
        available = w[1] - cursor
        if remaining <= available:
            return cursor + remaining
        remaining -= available
        cursor = next_opening(w[1], cfg)
    return cursor + remaining


def working_minutes_between(a_utc: datetime, b_utc: datetime, cfg: dict) -> float:
    """Minutes of working time in [a, b]. 0 if b <= a."""
    if b_utc <= a_utc:
        return 0.0
    total = timedelta(0)
    day = to_ist(a_utc).date()
    last = to_ist(b_utc).date()
    any_window = False
    while day <= last:
        w = _window_for_day(day, cfg)
        if w:
            any_window = True
            lo, hi = max(a_utc, w[0]), min(b_utc, w[1])
            if hi > lo:
                total += hi - lo
        day += timedelta(days=1)
    if not any_window and not cfg.get("days"):
        return (b_utc - a_utc).total_seconds() / 60
    return total.total_seconds() / 60
