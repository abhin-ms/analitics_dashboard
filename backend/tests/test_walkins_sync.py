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


# ── team leaders' lead sheets: one tab per store, found by themselves ──
from app.services import tele_call_sync  # noqa: E402
from app.services.store_portfolio import area_of_sheet, shop_of_sheet  # noqa: E402

LEAD_HEADER = ["Lead Source", "Created Time", "Full Name", "Phone number", "Email", "Person Calling", "Status",
               "Call date", "Appointment Date", "Remarks", "Sale Amount", "Product", "Follow ups", "Bill No"]


def test_lead_tabs_are_discovered_and_named_for_their_store(monkeypatch):
    book = {
        "Kochi": [LEAD_HEADER, ["PM", "2026-10-01T10:00:00+05:30", "Asha", "p:+919876500001", "", "", "Will Visit", "", "", "", "", "", "2", "117180"]],
        "Kochi Follow up": [["Full Name", "Phone Number", "Email", "Current status"], ["#N/A"]],
        "TVM": [LEAD_HEADER],                                   # a store with no leads yet is still a sheet
        "Status Options": [["Call Not Connected", "", "Not answering"]],
    }
    monkeypatch.setattr(tele_call_sync, "TL_SPREADSHEETS", [{"spreadsheet_id": "S1", "team_leader": "MICHAEL"}])
    monkeypatch.setattr(tele_call_sync, "TELE_CALL_SHEETS", [])
    monkeypatch.setattr(tele_call_sync, "_fetch_spreadsheet", lambda sid: book)
    sheets = tele_call_sync.refresh_sheet_list()
    assert [(c["tab"], c["tl_name"], c["team_leader"]) for c in sheets] == [("Kochi", "Kochi", "MICHAEL"), ("TVM", "Trivandrum", "MICHAEL")]
    assert tele_call_sync.sheet_key(sheets[1]) == "S1#TVM"
    rows = tele_call_sync._fetch_sheet_rows("S1", "Kochi")
    assert len(rows) == 1 and rows[0]["full_name"] == "Asha" and rows[0]["bill_no"] == "117180"   # extra columns don't shift anything
    assert tele_call_sync._fetch_sheet_rows("S1", "TVM") == []


def test_a_spreadsheet_that_cannot_be_read_keeps_its_tabs(monkeypatch):
    kept = [{"spreadsheet_id": "S1", "tab": "Kochi", "tl_name": "Kochi", "team_leader": "MICHAEL"}]
    monkeypatch.setattr(tele_call_sync, "TL_SPREADSHEETS", [{"spreadsheet_id": "S1", "team_leader": "MICHAEL"}])
    monkeypatch.setattr(tele_call_sync, "TELE_CALL_SHEETS", list(kept))

    def boom(_sid):
        raise RuntimeError("quota")
    monkeypatch.setattr(tele_call_sync, "_fetch_spreadsheet", boom)
    assert tele_call_sync.refresh_sheet_list() == kept


def test_store_tabs_put_leads_on_their_store():
    assert [shop_of_sheet(s) for s in ("Kochi", "Trivandrum", "Hitech City", "Thane", "Kasaragod", "Delhi")] == [
        "kochi", "trivandrum", "hitech_city", "korum", "kasaragod", "delhi"]
    assert shop_of_sheet("Bangalore") is None and area_of_sheet("Bangalore") == "karnataka"   # one tab, two shops
    assert area_of_sheet("Thrissur") == "kerala" and area_of_sheet("Bandra") == "north"


def test_lead_sheet_cells_are_cut_to_column_size(monkeypatch):
    """A customer who pastes a paragraph as their name must not fail the sync."""
    from app.services import tele_call_sync
    header = ["Lead Source", "Created Time", "Full Name", "Phone number", "Email", "Person Calling", "Status",
              "Call date", "Appointment Date", "Remarks", "Sale Amount", "Product"]
    row = ["GM", "2026-10-15T06:33:27-05:00", "x" * 1500, "p:+918300000000", "a@b.c", "Ashok", "Will Visit",
           "", "", "r" * 3000, "", ""]
    monkeypatch.setattr(tele_call_sync, "_fetch_spreadsheet", lambda _sid: {"Hitech": [header, row]})
    [lead] = tele_call_sync._fetch_sheet_rows("sheet", "Hitech")
    assert len(lead["full_name"]) == 200
    assert len(lead["remarks"]) == 3000  # unlimited text column: kept whole
    assert lead["phone"] == "p:+918300000000"
