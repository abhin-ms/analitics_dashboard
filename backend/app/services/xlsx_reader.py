"""Download and parse .xlsx files from Google Drive using service account."""
import calendar
import io
import os
import re
import time
import logging
from datetime import date, datetime
from typing import Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_httplib2 import AuthorizedHttp
import httplib2
import openpyxl

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

HTTP_TIMEOUT = 120
MAX_RETRIES = 4
RETRY_BACKOFF_BASE = 2.0

_drive_service = None


def _get_drive_service():
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    sa_path = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        os.path.join(os.path.dirname(__file__), "..", "..", "bp-analytics-sync-75ca3b0a13a4.json"),
    )
    if not os.path.exists(sa_path):
        raise FileNotFoundError(f"Service account JSON not found: {sa_path}")
    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=DRIVE_SCOPES)
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=HTTP_TIMEOUT))
    _drive_service = build("drive", "v3", http=http, cache_discovery=False)
    return _drive_service


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, ConnectionError, ConnectionResetError, OSError))


def download_xlsx(file_id: str) -> io.BytesIO:
    """Download an xlsx file from Google Drive by file ID with retries on transient errors."""
    drive = _get_drive_service()
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            request = drive.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            buf.seek(0)
            return buf
        except (TimeoutError, ConnectionError, ConnectionResetError, OSError) as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Drive download retry %d/%d for %s after error %r; waiting %.1fs",
                    attempt + 1, MAX_RETRIES, file_id, e, wait,
                )
                time.sleep(wait)
    raise last_exc


def _parse_from_buf(buf: io.BytesIO):
    wb = openpyxl.load_workbook(buf, read_only=True, data_only=True)
    return wb


def parse_daily_input(file_id: str) -> list[dict]:
    """Download xlsx and parse the 'Daily Input' tab into a list of dicts."""
    buf = download_xlsx(file_id)
    return parse_daily_input_buf(buf)


# Daily Input columns, found by (section banner, header text) instead of by
# position — the sheet has gained unlabelled spacer columns before (e.g. the
# blank column after "Followers (total)"), and a fixed index silently shifts
# every later field by one (Google rating read from Walkins, etc.).
# Each entry: field -> (section, header prefixes, kind). Section None = any.
_DAILY_INPUT_COLUMNS: dict[str, tuple[Optional[str], tuple[str, ...], str]] = {
    "date": (None, ("date",), "str"),
    "store": (None, ("store name",), "str"),
    "country": (None, ("country",), "str"),
    "store_type": (None, ("store type",), "str"),
    "daily_revenue": ("SALES", ("daily revenue",), "num"),
    "monthly_target": ("SALES", ("monthly target",), "num"),
    "mtd_revenue": ("SALES", ("mtd revenue",), "num"),
    "units_sold": ("SALES", ("units sold",), "int"),
    "care_plus_attached": ("SALES", ("care plus",), "int"),
    "prebookings": ("SALES", ("prebooking",), "int"),
    "ig_videos_posted": ("INSTAGRAM", ("total videos posted",), "int"),
    "ig_views_target": ("INSTAGRAM", ("total views target",), "num"),
    "ig_views_achieved": ("INSTAGRAM", ("total views achieved",), "num"),
    "ig_views_achd_pct": ("INSTAGRAM", ("achd",), "num"),
    "ig_followers": ("INSTAGRAM", ("followers (total)", "followers"), "int"),
    "ig_new_followers": ("INSTAGRAM", ("new followers",), "int"),
    "ig_likes": ("INSTAGRAM", ("likes",), "int"),
    "ig_comments": ("INSTAGRAM", ("comments",), "int"),
    "ig_saves": ("INSTAGRAM", ("saves",), "int"),
    "ig_shares": ("INSTAGRAM", ("shares",), "int"),
    "ig_reposts": ("INSTAGRAM", ("repost", "reshare"), "int"),
    "ig_dms_received": ("INSTAGRAM", ("dms received", "dms"), "int"),
    "ig_manychat_handled": ("INSTAGRAM", ("manychat",), "int"),
    "ig_posts_published": ("INSTAGRAM", ("posts published",), "int"),
    "yt_views": ("YOUTUBE", ("views",), "int"),
    "yt_likes": ("YOUTUBE", ("likes",), "int"),
    "yt_comments": ("YOUTUBE", ("comments",), "int"),
    "tt_views": ("TIKTOK", ("views",), "int"),
    "tt_likes": ("TIKTOK", ("likes",), "int"),
    "tt_followers": ("TIKTOK", ("followers",), "int"),
    "sc_views": ("SNAPCHAT", ("views",), "int"),
    "sc_shares": ("SNAPCHAT", ("shares",), "int"),
    # Not in the sheet yet — picked up as soon as a FACEBOOK section with a
    # "Views" column is added to Daily Input.
    "fb_views": ("FACEBOOK", ("views",), "int"),
    "wa_chats_received": ("WHATSAPP", ("overall wa chats", "wa chats"), "int"),
    "wa_walkins_booked": (None, ("walkins booked", "walk-ins booked"), "int"),
    "google_rating": (None, ("google rating",), "num"),
    "google_new_reviews": (None, ("new reviews",), "int"),
    "google_review_response": (None, ("review response",), "str"),
}

# Positions used before the header lookup existed, kept as the fallback for a
# sheet whose header row can't be read.
_DAILY_INPUT_LEGACY_ORDER = [
    "date", "store", "country", "store_type", "daily_revenue", "monthly_target",
    "mtd_revenue", "units_sold", "care_plus_attached", "prebookings",
    "ig_videos_posted", "ig_views_target", "ig_views_achieved", "ig_views_achd_pct",
    "ig_followers", "ig_new_followers", "ig_likes", "ig_comments", "ig_saves",
    "ig_shares", "ig_reposts", "ig_dms_received", "ig_manychat_handled",
    "ig_posts_published", "yt_views", "yt_likes", "yt_comments", "tt_views",
    "tt_likes", "tt_followers", "sc_views", "sc_shares", "wa_chats_received",
    "wa_walkins_booked", "google_rating", "google_new_reviews", "google_review_response",
]


def _daily_input_column_map(section_row, header_row) -> dict[str, int]:
    """Map each Daily Input field to its column index from the two header rows."""
    sections: list[str] = []
    current = ""
    for i in range(len(header_row)):
        banner = section_row[i] if i < len(section_row) else None
        if banner and str(banner).strip():
            current = str(banner).strip().upper()
        sections.append(current)
    headers = [str(h).strip().lower() if h else "" for h in header_row]

    taken: set[int] = set()
    col_map: dict[str, int] = {}
    # Longer prefixes first, so "new followers" claims its column before the
    # generic "followers" prefix can.
    specs = sorted(_DAILY_INPUT_COLUMNS.items(), key=lambda kv: -max(len(p) for p in kv[1][1]))
    for field, (section, prefixes, _kind) in specs:
        for prefix in prefixes:
            idx = next(
                (i for i, h in enumerate(headers)
                 if i not in taken and h.startswith(prefix)
                 and (section is None or sections[i].startswith(section))),
                None,
            )
            if idx is not None:
                col_map[field] = idx
                taken.add(idx)
                break
    return col_map


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def normalize_tracker_date(val) -> str:
    """Turn a Daily Input date cell into an ISO date string.

    Store managers enter a single day ("15-Aug-2026", a real date cell) or, for
    a month summary row, a range like "01 to 31-Aug-2026" — that becomes the
    range's last day, the date the totals are "as of". Anything unrecognised
    is returned as-is so the row is still stored."""
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    s = str(val).strip()
    m = re.match(r"^(?:\d{1,2}\s*(?:to|-|–)\s*)?(\d{1,2})[\s/-]+([A-Za-z]{3,})[\s/-]+(\d{4})$", s, re.I)
    if m and m.group(2)[:3].lower() in _MONTHS:
        year, month = int(m.group(3)), _MONTHS[m.group(2)[:3].lower()]
        # "01 to 31-Sept-2026": a month-end typed as 31 for a 30-day month
        # still means the last day of that month.
        day = min(int(m.group(1)), calendar.monthrange(year, month)[1])
        return date(year, month, day).isoformat() if day >= 1 else s
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def parse_daily_input_buf(buf: io.BytesIO) -> list[dict]:
    """Parse the 'Daily Input' tab from an already-downloaded xlsx buffer."""
    wb = _parse_from_buf(buf)

    if "Daily Input" not in wb.sheetnames:
        logger.error("Daily Input tab not found in xlsx")
        return []

    ws = wb["Daily Input"]
    rows = list(ws.iter_rows(values_only=True))

    if len(rows) < 5:
        return []

    col_map = _daily_input_column_map(rows[2], rows[3])
    if "store" not in col_map or "date" not in col_map:
        logger.warning("Daily Input header row not recognised; falling back to fixed column positions")
        col_map = {f: i for i, f in enumerate(_DAILY_INPUT_LEGACY_ORDER)}

    def cell(row, field):
        i = col_map.get(field)
        return row[i] if i is not None and i < len(row) else None

    data = []
    for row in rows[4:]:
        if not row or len(row) < 10:
            continue
        store_name = cell(row, "store")
        if not store_name or not str(store_name).strip():
            continue

        rec: dict = {}
        for field, (_section, _prefixes, kind) in _DAILY_INPUT_COLUMNS.items():
            v = cell(row, field)
            if kind == "num":
                rec[field] = _num(v)
            elif kind == "int":
                rec[field] = _int(v)
            else:
                rec[field] = str(v).strip() if v is not None and str(v).strip() else ""
        rec["store"] = str(store_name).strip()
        rec["date"] = normalize_tracker_date(cell(row, "date"))
        data.append(rec)

    wb.close()
    return data


def parse_store_dashboard(file_id: str) -> list[dict]:
    """Download xlsx and parse the 'Store Dashboard' tab for summary/status data."""
    buf = download_xlsx(file_id)
    return parse_store_dashboard_buf(buf)


def parse_store_dashboard_buf(buf: io.BytesIO) -> list[dict]:
    """Parse the 'Store Dashboard' tab from an already-downloaded xlsx buffer."""
    wb = _parse_from_buf(buf)

    if "Store Dashboard" not in wb.sheetnames:
        return []

    ws = wb["Store Dashboard"]
    rows = list(ws.iter_rows(values_only=True))

    if len(rows) < 5:
        return []

    data = []
    for row in rows[4:]:
        if not row or len(row) < 5:
            continue
        store_name = row[0] if row[0] else ""
        if not store_name or not str(store_name).strip():
            continue

        data.append({
            "store": str(store_name).strip(),
            "country": str(row[1]).strip() if len(row) > 1 and row[1] else "",
            "mtd_revenue": _num(row[2]) if len(row) > 2 else None,
            "monthly_target": _num(row[3]) if len(row) > 3 else None,
            "target_pct": _num(row[4]) if len(row) > 4 else None,
            "care_plus_pct": _num(row[5]) if len(row) > 5 else None,
            "total_views": _int(row[6]) if len(row) > 6 else None,
            "engagements": _int(row[7]) if len(row) > 7 else None,
            "eng_rate_pct": _num(row[8]) if len(row) > 8 else None,
            "prebookings": _int(row[9]) if len(row) > 9 else None,
            "dms_received": _int(row[10]) if len(row) > 10 else None,
            "wa_response_pct": _num(row[11]) if len(row) > 11 else None,
            "walkins_booked": _int(row[12]) if len(row) > 12 else None,
            "insta_followers": _int(row[13]) if len(row) > 13 else None,
            "follower_growth": _int(row[14]) if len(row) > 14 else None,
            "google_rating": _num(row[15]) if len(row) > 15 else None,
            "new_reviews": _int(row[16]) if len(row) > 16 else None,
            "sales_status": str(row[17]).strip() if len(row) > 17 and row[17] else "",
            "marketing_status": str(row[18]).strip() if len(row) > 18 and row[18] else "",
        })

    wb.close()
    return data


def _num(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("₹", "").replace("%", "").replace("—", "")
    if not s or s.lower() in ("n/a", "—", "-", "none"):
        return None
    # Hand-typed cells like "370+" or "49 ( till 15 )" — keep the leading number.
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*(?:\+|\(.*\))?$", s)
    if not m:
        return None
    return float(m.group(1))


def _int(val) -> Optional[int]:
    n = _num(val)
    return int(n) if n is not None else None
