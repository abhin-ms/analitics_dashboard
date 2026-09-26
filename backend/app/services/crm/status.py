"""Single source of truth for tele-call lead statuses, pipeline stages,
priorities and call outcomes.

Contact *status* is what the sheet's "Status" column holds (and what the
existing pages show). Pipeline *stage* and *priority* are app-owned and are
derived from status unless someone set them by hand.
"""
from __future__ import annotations

import re

NO_STATUS = "No Status"

# The vocabulary already used by the sheets and the existing pages
# (TeleCallLeads.tsx STATUS_OPTIONS). Order = display order.
STATUSES: list[str] = [
    "Call Not Connected",
    "Call back later",
    "Not Interested",
    "Will Visit",
    "Appointment",
    "Sale Conversion",
    "Wrong number",
    "Unattended",
]

# Statuses that mean the call did NOT connect (used for connected-rate maths).
NOT_CONNECTED_STATUSES = {"Call Not Connected", "Wrong number", "Unattended"}
# Leads still being worked (used by the "Active Leads" KPI).
ACTIVE_STATUSES = {"Call back later", "Will Visit", "Appointment"}
# Statuses that end the contact sequence.
CLOSED_STATUSES = {"Sale Conversion", "Not Interested", "Wrong number"}
# "Needs follow-up" group shown on the admin Leads page.
FOLLOW_UP_STATUSES = {"Call Not Connected", "Unattended", "Call back later"}


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


_VARIANTS: dict[str, str] = {}
for _s in STATUSES:
    _VARIANTS[_key(_s)] = _s
_VARIANTS.update({
    "notconnected": "Call Not Connected",
    "callnotconnect": "Call Not Connected",
    "cnc": "Call Not Connected",
    "notreachable": "Call Not Connected",
    "noanswer": "Call Not Connected",
    "switchedoff": "Call Not Connected",
    "busy": "Call Not Connected",
    "callback": "Call back later",
    "callbacklatter": "Call back later",
    "cbl": "Call back later",
    "callbacklaterr": "Call back later",
    "ni": "Not Interested",
    "notintrested": "Not Interested",
    "notinterest": "Not Interested",
    "willvist": "Will Visit",
    "visit": "Will Visit",
    "appointmentbooked": "Appointment",
    "appt": "Appointment",
    "appoinment": "Appointment",
    "sale": "Sale Conversion",
    "sold": "Sale Conversion",
    "converted": "Sale Conversion",
    "saleconverted": "Sale Conversion",
    "salesconversion": "Sale Conversion",
    "wrongno": "Wrong number",
    "invalidnumber": "Wrong number",
    "wrongnumbers": "Wrong number",
    "notattended": "Unattended",
    "unatended": "Unattended",
    "nostatus": "",
})


def normalize_status(raw: str | None) -> str:
    """Map a sheet/app status to the canonical spelling.

    Case, spacing and punctuation are ignored and common variants are merged.
    Unknown values are kept (trimmed) rather than dropped, so nothing is lost;
    Data Quality lists them. Empty stays empty ("No Status" is display-only).
    """
    text = (raw or "").strip()
    if not text:
        return ""
    return _VARIANTS.get(_key(text), text)


def display_status(status: str | None) -> str:
    return status or NO_STATUS


def is_known_status(status: str | None) -> bool:
    return not status or status in STATUSES


# ── Pipeline stages ─────────────────────────────────────────────────
STAGES: list[dict] = [
    {"key": "new", "label": "New"},
    {"key": "contacting", "label": "Contacting"},
    {"key": "qualified", "label": "Qualified"},
    {"key": "paid_advance", "label": "Paid Advance"},
    {"key": "converted", "label": "Converted Customer"},
    {"key": "not_interested", "label": "Not Interested"},
]
STAGE_KEYS = [s["key"] for s in STAGES]
STAGE_LABELS = {s["key"]: s["label"] for s in STAGES}
OPEN_STAGE_ORDER = {"new": 0, "contacting": 1, "qualified": 2, "paid_advance": 3}
CLOSED_STAGES = {"converted", "not_interested"}

_STATUS_STAGE = {
    "": "new",
    "Call Not Connected": "contacting",
    "Unattended": "contacting",
    "Call back later": "contacting",
    "Will Visit": "qualified",
    "Appointment": "qualified",
    "Sale Conversion": "converted",
    "Not Interested": "not_interested",
    "Wrong number": "not_interested",
}


def stage_for_status(status: str | None) -> str:
    return _STATUS_STAGE.get(status or "", "contacting")


def derive_stage(status: str | None, current: str | None, manual: bool = False) -> str:
    """Stage implied by a status.

    Closing statuses (converted / not interested) always apply. Otherwise a
    manual stage wins, and the automatic stage only moves forward — a Paid
    Advance lead that goes back to "Will Visit" stays Paid Advance. A closed
    lead whose status becomes an open one again is re-opened.
    """
    target = stage_for_status(status)
    if target in CLOSED_STAGES:
        return target
    if current in CLOSED_STAGES or not current:
        return target
    if manual:
        return current
    if OPEN_STAGE_ORDER.get(current, 0) >= OPEN_STAGE_ORDER.get(target, 0):
        return current
    return target


# ── Priority ───────────────────────────────────────────────────────
PRIORITIES = ["hot", "warm", "cold"]


def derive_priority(stage: str | None, current: str | None = None, manual: bool = False) -> str:
    """Paid Advance is Hot, Not Interested is Cold, everything else Warm
    (the mockup's "Will Visit is Warm; Paid Advance is Hot")."""
    if manual and current in PRIORITIES:
        return current
    if stage == "paid_advance":
        return "hot"
    if stage == "not_interested":
        return "cold"
    return "warm"


# ── Call outcomes (Log activity) ───────────────────────────────────
# status: the contact status the outcome sets (None = unchanged)
# closes: stops the contact sequence (cancels open follow-ups)
# connected: the call reached the customer
OUTCOMES: dict[str, dict] = {
    "no_answer": {"label": "No answer", "status": "Call Not Connected", "connected": False},
    "switched_off": {"label": "Switched off", "status": "Call Not Connected", "connected": False},
    "busy": {"label": "Busy", "status": "Call Not Connected", "connected": False},
    "wrong_number": {"label": "Wrong number", "status": "Wrong number", "connected": False, "closes": True},
    "callback_requested": {"label": "Callback requested", "status": "Call back later", "connected": True},
    "will_visit": {"label": "Will visit", "status": "Will Visit", "connected": True},
    "appointment_booked": {"label": "Appointment booked", "status": "Appointment", "connected": True},
    "advance_paid": {"label": "Advance paid", "status": None, "connected": True, "stage": "paid_advance"},
    "converted": {"label": "Converted (sale)", "status": "Sale Conversion", "connected": True, "closes": True},
    "not_interested": {"label": "Not interested", "status": "Not Interested", "connected": True, "closes": True},
    "connected_other": {"label": "Connected – other", "status": None, "connected": True},
    "note": {"label": "Note only", "status": None, "connected": None, "is_note": True},
}

# Maps a status change that arrived from the SHEET to the outcome whose
# scheduling rule should apply (the agent updated the sheet, not the app).
STATUS_TO_OUTCOME = {
    "Call Not Connected": "no_answer",
    "Unattended": "no_answer",
    "Call back later": "callback_requested",
    "Will Visit": "will_visit",
    "Appointment": "appointment_booked",
    "Sale Conversion": "converted",
    "Not Interested": "not_interested",
    "Wrong number": "wrong_number",
}
