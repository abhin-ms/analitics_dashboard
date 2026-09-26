"""Unit tests for the telecalling CRM rules (pure functions, no database)."""
from datetime import datetime, timedelta

import pytest

from app.services.crm.config import DEFAULT_AUTOMATION
from app.services.crm.engine import match_user_by_name, next_step_for_outcome, norm_phone
from app.services.crm.status import (
    derive_priority, derive_stage, normalize_status, stage_for_status,
)
from app.services.crm.timeutil import (
    add_working_minutes, from_ist, is_working_time, next_opening, next_working_day_opening,
    parse_sheet_datetime, to_ist, working_minutes_between,
)

WH = DEFAULT_AUTOMATION["working_hours"]  # Mon–Sat 09:00–18:00 IST


def ist(y, m, d, h=0, mi=0):
    """naive UTC for an IST wall-clock time"""
    return from_ist(datetime(y, m, d, h, mi))


# 2026-09-24 is a Thursday, 2026-09-26 a Saturday, 2026-09-27 a Sunday.


class TestStatus:
    @pytest.mark.parametrize("raw,expected", [
        ("Call back later", "Call back later"),
        ("call back later", "Call back later"),
        ("  CALL BACK LATER ", "Call back later"),
        ("Callback", "Call back later"),
        ("not interested", "Not Interested"),
        ("Will visit", "Will Visit"),
        ("sale conversion", "Sale Conversion"),
        ("Wrong Number", "Wrong number"),
        ("call not connected", "Call Not Connected"),
        ("", ""),
        (None, ""),
        ("No Status", ""),
        ("Something new", "Something new"),  # unknown values are kept, never dropped
    ])
    def test_normalize(self, raw, expected):
        assert normalize_status(raw) == expected

    def test_stage_mapping(self):
        assert stage_for_status("") == "new"
        assert stage_for_status("Call Not Connected") == "contacting"
        assert stage_for_status("Will Visit") == "qualified"
        assert stage_for_status("Sale Conversion") == "converted"
        assert stage_for_status("Wrong number") == "not_interested"

    def test_stage_only_moves_forward(self):
        # Paid Advance lead that goes back to "Will Visit" stays Paid Advance
        assert derive_stage("Will Visit", "paid_advance") == "paid_advance"
        assert derive_stage("Call back later", "qualified") == "qualified"
        assert derive_stage("Will Visit", "contacting") == "qualified"

    def test_closing_status_always_applies(self):
        assert derive_stage("Sale Conversion", "paid_advance", manual=True) == "converted"
        assert derive_stage("Not Interested", "qualified", manual=True) == "not_interested"

    def test_closed_lead_reopens(self):
        assert derive_stage("Call back later", "not_interested") == "contacting"

    def test_manual_stage_wins_for_open_statuses(self):
        assert derive_stage("Call Not Connected", "qualified", manual=True) == "qualified"

    def test_priority(self):
        assert derive_priority("paid_advance") == "hot"
        assert derive_priority("qualified") == "warm"
        assert derive_priority("not_interested") == "cold"
        assert derive_priority("qualified", "hot", manual=True) == "hot"


class TestSheetDates:
    def test_meta_iso_with_offset(self):
        assert parse_sheet_datetime("2026-09-24T10:00:00+05:30") == datetime(2026, 9, 24, 4, 30)

    def test_iso_utc_z(self):
        assert parse_sheet_datetime("2026-09-24T04:30:00Z") == datetime(2026, 9, 24, 4, 30)

    def test_compact_offset(self):
        assert parse_sheet_datetime("2026-09-24T10:00:00+0530") == datetime(2026, 9, 24, 4, 30)

    def test_naive_is_ist(self):
        assert parse_sheet_datetime("2026-09-24 10:00") == ist(2026, 9, 24, 10, 0)

    def test_indian_day_month_order(self):
        assert parse_sheet_datetime("05/09/2026") == ist(2026, 9, 5)
        assert parse_sheet_datetime("24-09-2026 2:30 PM") == ist(2026, 9, 24, 14, 30)

    def test_month_day_only_when_unambiguous(self):
        assert parse_sheet_datetime("9/24/2026 10:00:00") == ist(2026, 9, 24, 10, 0)

    def test_month_names(self):
        assert parse_sheet_datetime("24 Sep 2026") == ist(2026, 9, 24)
        assert parse_sheet_datetime("Sep 24, 2026 11:30") == ist(2026, 9, 24, 11, 30)

    @pytest.mark.parametrize("bad", ["", "tomorrow", "31/02/2026", "abc 12"])
    def test_unreadable(self, bad):
        assert parse_sheet_datetime(bad) is None


class TestWorkingHours:
    def test_is_working_time(self):
        assert is_working_time(ist(2026, 9, 24, 10, 0), WH)
        assert not is_working_time(ist(2026, 9, 24, 8, 59), WH)
        assert not is_working_time(ist(2026, 9, 27, 11, 0), WH)  # Sunday

    def test_five_minutes_inside_hours(self):
        assert add_working_minutes(ist(2026, 9, 24, 10, 0), 5, WH) == ist(2026, 9, 24, 10, 5)

    def test_after_hours_lead_waits_for_opening(self):
        # arrives 22:00 Thursday → due Friday 09:05
        assert add_working_minutes(ist(2026, 9, 24, 22, 0), 5, WH) == ist(2026, 9, 25, 9, 5)

    def test_spills_over_closing_time(self):
        # 17:58 Saturday + 5 → Monday 09:03 (Sunday is off)
        assert add_working_minutes(ist(2026, 9, 26, 17, 58), 5, WH) == ist(2026, 9, 28, 9, 3)

    def test_minutes_between_only_counts_working_time(self):
        assert working_minutes_between(ist(2026, 9, 24, 17, 50), ist(2026, 9, 25, 9, 10), WH) == 20
        assert working_minutes_between(ist(2026, 9, 24, 10, 0), ist(2026, 9, 24, 10, 15), WH) == 15
        assert working_minutes_between(ist(2026, 9, 27, 10, 0), ist(2026, 9, 27, 12, 0), WH) == 0

    def test_next_opening_and_next_day(self):
        assert next_opening(ist(2026, 9, 24, 7, 0), WH) == ist(2026, 9, 24, 9, 0)
        assert next_opening(ist(2026, 9, 24, 12, 0), WH) == ist(2026, 9, 24, 12, 0)
        assert next_working_day_opening(ist(2026, 9, 26, 12, 0), WH) == ist(2026, 9, 28, 9, 0)

    def test_round_trip(self):
        t = ist(2026, 9, 24, 10, 0)
        assert to_ist(t).hour == 10


class TestOutcomeRules:
    now = ist(2026, 9, 24, 11, 0)  # Thursday 11:00 IST

    def step(self, outcome, **kw):
        return next_step_for_outcome(outcome, self.now, DEFAULT_AUTOMATION, **kw)

    def test_no_answer_retries_in_three_and_half_hours(self):
        due, kind, _ = self.step("no_answer")
        assert (due, kind) == (ist(2026, 9, 24, 14, 30), "call")

    def test_switched_off_retries_next_working_day(self):
        due, _, _ = self.step("switched_off")
        assert due == ist(2026, 9, 25, 9, 0)

    def test_busy_retries_in_45_minutes(self):
        due, _, _ = self.step("busy", calls_so_far_today=1)
        assert due == ist(2026, 9, 24, 11, 45)

    def test_busy_never_more_than_two_calls_a_day(self):
        due, _, reason = self.step("busy", calls_so_far_today=2)
        assert due == ist(2026, 9, 25, 9, 0)
        assert "2 calls" in reason

    def test_callback_uses_customer_time(self):
        when = ist(2026, 9, 24, 16, 15)
        due, kind, _ = self.step("callback_requested", callback_at=when)
        assert (due, kind) == (when, "callback")

    def test_appointment_confirmation_two_hours_before(self):
        appt = ist(2026, 9, 25, 12, 0)
        due, kind, _ = self.step("appointment_booked", appointment_at=appt)
        assert (due, kind) == (ist(2026, 9, 25, 10, 0), "appointment_confirm")

    @pytest.mark.parametrize("outcome", ["not_interested", "converted", "wrong_number", "note"])
    def test_closing_outcomes_stop_the_sequence(self, outcome):
        assert self.step(outcome)[0] is None


class TestNameMatching:
    members = [{"id": 1, "name": "Sureka K"}, {"id": 2, "name": "Riya Menon"}, {"id": 3, "name": "Sam"}]

    def test_exact_case_insensitive(self):
        assert match_user_by_name("sureka k", self.members, {})["id"] == 1

    def test_unique_first_name(self):
        assert match_user_by_name("Riya", self.members, {})["id"] == 2

    def test_alias_wins(self):
        assert match_user_by_name("Suri", self.members, {"suri": 1})["id"] == 1

    def test_no_match(self):
        assert match_user_by_name("Unknown Person", self.members, {}) is None
        assert match_user_by_name("", self.members, {}) is None

    def test_phone_normalisation(self):
        assert norm_phone("+91 98765-43210") == "9876543210"
        assert norm_phone("p:+919876543210") == "9876543210"
