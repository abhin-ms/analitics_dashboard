import io
from datetime import datetime

import openpyxl

from app.services.xlsx_reader import normalize_tracker_date, parse_daily_input_buf, _num

SECTIONS = ["STORE INFO", None, None, None, "SALES", None, None, None, None, None,
            "INSTAGRAM"] + [None] * 14 + ["YOUTUBE", None, None, "TIKTOK", None, None,
            "SNAPCHAT", None, "WHATSAPP ", None, "GOOGLE", None, None]
HEADERS = ["Date", "Store Name", "Country", "Store Type", "Daily Revenue (₹)", "Monthly Target (₹)",
           "MTD Revenue (₹)", "Units Sold", "Care Plus Attached", "Prebookings (₹99)",
           "Total Videos Posted", "Total Views Target", "Total Views achieved", "Achd %",
           "Followers (total)", None, "New Followers", "Likes", "Comments", "Saves", "Shares",
           "Repost", "DMs Received", "Manychat Handled", "Posts Published",
           "Views", "Likes", "Comments", "Views", "Likes", "Followers", "Views", "Shares",
           "Overall WA Chats Received", "Walkins Booked", "Google Rating", "New Reviews",
           "Review Response Done?"]


def _book(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Daily Input"
    ws.append(["BREAK PROTECTION — Daily Store Data Entry"])
    ws.append([])
    ws.append(SECTIONS)
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_daily_input_columns_found_by_header_despite_blank_spacer_column():
    row = ["01 to 31-Aug-2026", "Kerala Kochi", "IN", "Mall Kiosk", 29041, 925000, 360427, None, None, None,
           1, 1000000, 16400, 0.0164, 78, None, 26, 9, 0, 158, 498, 6, 3, 0, 4,
           None, None, None, None, None, None, None, None, 1600, 99, 4.4, 310, "Partial"]
    [rec] = parse_daily_input_buf(_book([row]))
    assert rec["date"] == "2026-08-31"
    assert rec["ig_followers"] == 78
    assert rec["ig_new_followers"] == 26
    assert rec["ig_likes"] == 9
    assert rec["ig_reposts"] == 6
    assert rec["ig_posts_published"] == 4
    assert rec["yt_views"] is None
    assert rec["wa_chats_received"] == 1600
    assert rec["wa_walkins_booked"] == 99
    assert rec["google_rating"] == 4.4
    assert rec["google_new_reviews"] == 310
    assert rec["google_review_response"] == "Partial"


def test_hand_typed_numbers():
    assert _num("370+") == 370
    assert _num("49 ( till 15 )") == 49
    assert _num("1,600") == 1600
    assert _num("-") is None
    assert _num("approx 18K") is None


def test_normalize_tracker_date():
    assert normalize_tracker_date("01 to 31-Aug-2026") == "2026-08-31"
    assert normalize_tracker_date("1 - 15 Sep 2026") == "2026-09-15"
    assert normalize_tracker_date("15-Aug-2026") == "2026-08-15"
    assert normalize_tracker_date(datetime(2026, 8, 5)) == "2026-08-05"
    assert normalize_tracker_date("2026-08-05") == "2026-08-05"
    assert normalize_tracker_date(None) == ""
