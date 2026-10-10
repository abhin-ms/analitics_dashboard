"""Walk-ins Data sheet: tab parsing (pure) and the store matching rules."""
from datetime import date

from app.services.store_portfolio import shop_of
from app.services.walkins_sync import parse_walkins_tab

TAB = [
    ["October"],
    [],
    ["Date", "Nagarani", "", "", "", "Harsh"],
    ["", "Indiranagar", "", "", "", "Calicut", "", "", "", "", "Mysore"],
    ["", "Actual Walkins", "Dsr Walkins", "Diff", "", "Actual Walkins", "Dsr Walkins", "Diff", "", "", "Actual Walkins", "Dsr Walkins"],
    ["01/10/2026", "21", "18", "", "", "", "20", "", "", "", "0", "0"],
    ["02/10/2026", "26", "", "", "", "", "", "", "", "", "", ""],
    ["09/10/2026"],
    ["Total", "47", "18", "0", "", "0", "20"],
]


def test_parses_each_store_day_and_skips_blank_and_total_rows():
    assert parse_walkins_tab(TAB) == [
        ("Indiranagar", date(2026, 10, 1), 21, 18),
        ("Calicut", date(2026, 10, 1), None, 20),       # only the DSR figure filled
        ("Mysore", date(2026, 10, 1), 0, 0),            # an explicit zero is still a report
        ("Indiranagar", date(2026, 10, 2), 26, None),
    ]


def test_header_row_position_can_move():
    assert parse_walkins_tab(TAB[1:])[0] == ("Indiranagar", date(2026, 10, 1), 21, 18)
    assert parse_walkins_tab([["no header"]]) == []


def test_sheet_spellings_map_to_shops():
    assert shop_of("Hitec city") == "hitech_city"
    assert shop_of("Pathanamathitta") == "pathanamthitta"
    assert shop_of("Korum Thane") == "korum"


from app.services.daily_submission_sync import parse_daily_submission  # noqa: E402

FORM = [
    ["Daily Target: ₹16,500"],
    ["DATE", "STORE NAME", "LEADS\n(Outbound)", "INBOUND\nLEADS", "CALLS\nMADE", "CONTACTS\nMADE", "APPTS\nSET",
     "WALK-\nINS", "HOME\nDELIVERIES", "IN-STORE\nSALES", "REVENUE\n₹", "PRICE\nTOO HIGH", "NO\nSHOW"],
    ["01-Aug-26", "Kerala Kochi", "", "18", "12", "9", "4", "6", "1", "4", "₹21,960", "2", "0"],
    ["02-Aug-26", "Kerala Kochi", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "-", "-"],
    ["Total", "x", "1"],
]


def test_daily_form_rows_only_once_filled():
    rows = parse_daily_submission(FORM)
    assert len(rows) == 1                      # 2 Aug is the sheet's empty pre-filled row
    r = rows[0]
    assert (r["date"], r["store"], r["revenue"], r["inbound_leads"], r["outbound_leads"]) == (
        date(2026, 8, 1), "Kerala Kochi", 21960.0, 18, None)
    assert (r["calls_made"], r["calls_connected"], r["walk_ins"], r["walk_in_conversions"]) == (12, 9, 6, 4)
    assert r["lost_reasons"] == {"Price too high": 2}
