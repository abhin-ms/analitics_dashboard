"""Fetch tele call leads from the TL Google Sheets and sync to DB."""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from ..models.models import TeleCallLead
from .google_sheets import _get_service

logger = logging.getLogger(__name__)

# Lead sheets: one spreadsheet per team leader, one tab per store. Every
# lead tab has the same columns:
# Lead Source | Created Time | Full Name | Phone number | Email |
# Person Calling | Status | Call date | Appointment Date | Remarks | Sale Amount | Product
# (+ optional extras such as "Follow ups" or "Bill No"). The "... Follow up"
# tabs are formula views of the lead tabs and are not synced.
TL_SPREADSHEETS = [
    {"spreadsheet_id": "16hQmLFME-ZA2OiIzbt8HmV2o8OTB4J3aKrs4U8GpH0s", "team_leader": "DEVIAHH"},
    {"spreadsheet_id": "1viO0nNPq-SDJXB29xM32AULi4qoK7PFKMQe4pW3HD4A", "team_leader": "SAM"},
    {"spreadsheet_id": "1Or2WJUUn_rsb3MKfRE83UJZYgQDiMA-CDvMJLtFCN10", "team_leader": "HARSH"},
    {"spreadsheet_id": "1SE8tGQgtEDz5Wo3jb1U9fsXzujD3GdKwYy01gRV2rQU", "team_leader": "NAZIL"},
    {"spreadsheet_id": "1TRA3RXhnXwIsvduSVJddsDprKcmmkUh6zuSrPQMsvAo", "team_leader": "MICHAEL"},
    {"spreadsheet_id": "1jR035-uTOEcshHGM4BBOFyMdPWhbGNlq9o19x3PhFlI", "team_leader": "ABDULLAH"},
]
# The lead tabs known when this was written, so the app has its sheet list
# before the first sync; refresh_sheet_list() then keeps it in step with the
# spreadsheets (a tab added for a new store is picked up by itself).
_KNOWN_TABS = {
    "DEVIAHH": ["Mysore", "Mangalore"],
    "SAM": ["Kodambakkam", "Coimbatore", "Velachery", "Thrissur", "Kannur"],
    "HARSH": ["Guwahati"],
    "NAZIL": ["BLR"],
    "MICHAEL": ["Calicut", "Kochi", "TVM", "Wayanad", "Kasargod"],
    "ABDULLAH": ["Hitech", "Kukatpally", "Bandra", "Thane", "Delhi"],
}
# Tab title → the sheet name the app shows and assigns people to.
TAB_LABELS = {"BLR": "Bangalore", "Hitech": "Hitech City", "TVM": "Trivandrum", "Kasargod": "Kasaragod"}


def _cfg(spreadsheet_id: str, team_leader: str, tab: str) -> dict:
    return {"spreadsheet_id": spreadsheet_id, "tab": tab, "tl_name": TAB_LABELS.get(tab.strip(), tab.strip()),
            "team_leader": team_leader}


TELE_CALL_SHEETS = [_cfg(sp["spreadsheet_id"], sp["team_leader"], tab)
                    for sp in TL_SPREADSHEETS for tab in _KNOWN_TABS[sp["team_leader"]]]


def sheet_key(cfg: dict) -> str:
    """Value stored in TeleCallLead.spreadsheet_id for rows of this sheet.
    Tabs of one spreadsheet get their own key so their leads never match
    each other during sync."""
    return f"{cfg['spreadsheet_id']}#{cfg['tab']}" if cfg.get("tab") else cfg["spreadsheet_id"]


def _is_lead_tab(rows: list[list[str]]) -> bool:
    return bool(rows and rows[0] and str(rows[0][0]).strip().lower().startswith("lead source"))


# One spreadsheet's tabs, read in a single request and kept for the sync
# that follows (Google allows 60 reads a minute; tab by tab would use 19).
_TAB_CACHE: dict[str, tuple[float, dict[str, list[list[str]]]]] = {}
_TAB_CACHE_SECONDS = 45


def _fetch_spreadsheet(spreadsheet_id: str) -> dict[str, list[list[str]]]:
    """{tab title: rows} for every tab of a spreadsheet, in two requests."""
    cached = _TAB_CACHE.get(spreadsheet_id)
    if cached and time.monotonic() - cached[0] < _TAB_CACHE_SECONDS:
        return cached[1]
    service = _get_service()
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    titles = [sh["properties"]["title"] for sh in meta.get("sheets", [])]
    res = service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=[f"'{t}'!A1:P5000" for t in titles]).execute()
    tabs = {t: [[str(c) for c in row] for row in vr.get("values", [])] for t, vr in zip(titles, res.get("valueRanges", []))}
    _TAB_CACHE[spreadsheet_id] = (time.monotonic(), tabs)
    return tabs


def refresh_sheet_list() -> list[dict]:
    """Re-read every team leader's spreadsheet and bring TELE_CALL_SHEETS in
    step with its lead tabs. A spreadsheet that can't be read keeps the tabs
    it had, so one bad read never drops a store's sheet."""
    fresh: list[dict] = []
    for sp in TL_SPREADSHEETS:
        try:
            tabs = _fetch_spreadsheet(sp["spreadsheet_id"])
            fresh += [_cfg(sp["spreadsheet_id"], sp["team_leader"], t) for t, rows in tabs.items() if _is_lead_tab(rows)]
        except Exception as e:
            logger.warning(f"Could not list tabs of {sp['team_leader']}'s lead sheet: {e}")
            fresh += [c for c in TELE_CALL_SHEETS if c["spreadsheet_id"] == sp["spreadsheet_id"]]
    if fresh:
        TELE_CALL_SHEETS[:] = fresh
    return TELE_CALL_SHEETS


COL_MAP = {
    0: "lead_source",
    1: "created_time",
    2: "full_name",
    3: "phone",
    4: "email",
    5: "person_calling",
    6: "status",
    7: "call_date",
    8: "appointment_date",
    9: "remarks",
    10: "sale_amount",
    11: "product",
}

# Size of each sheet field's column (remarks is unlimited text).
FIELD_LIMITS = {f: TeleCallLead.__table__.c[f].type.length for f in COL_MAP.values()
                if getattr(TeleCallLead.__table__.c[f].type, "length", None)}


def _fetch_sheet_rows(spreadsheet_id: str, tab: str | None = None) -> list[dict]:
    """The leads of one tab of a team leader's sheet (the first lead tab
    when no tab is named)."""
    tabs = _fetch_spreadsheet(spreadsheet_id)
    rows = tabs.get(tab) if tab else next((r for r in tabs.values() if _is_lead_tab(r)), [])
    if rows is None:
        raise ValueError(f"Tab {tab!r} not found in spreadsheet {spreadsheet_id}")

    if len(rows) < 2:
        return []

    # Optional "Bill No" column, wherever the team adds it after the 12
    # standard ones: the bill the lead bought with (see crm/bill_verify.py).
    bill_col = next((i for i, h in enumerate(rows[0]) if i >= len(COL_MAP) and "bill" in (h or "").lower()), None)

    leads = []
    for row in rows[1:]:
        if not row or not any(cell.strip() for cell in row[:len(COL_MAP)] if cell):
            continue
        record = {}
        for col_idx, field in COL_MAP.items():
            value = row[col_idx].strip() if col_idx < len(row) and row[col_idx] else ""
            # Cut to the column's size: one over-long cell (a customer pasted a
            # paragraph as their name) would otherwise fail the whole sync.
            record[field] = value[:FIELD_LIMITS[field]] if field in FIELD_LIMITS else value
        if bill_col is not None:
            record["bill_no"] = row[bill_col].strip()[:30] if bill_col < len(row) and row[bill_col] else ""
        # Skip rows with no name at all
        if not record.get("full_name"):
            continue
        leads.append(record)
    return leads


# Sheet fields the sync writes. When a lead was edited in the app
# (edited_by_user) the original behaviour is kept: only these three still
# follow the sheet...
SHEET_FIELDS_AFTER_APP_EDIT = {"lead_source", "product", "sale_amount", "bill_no"}

# Last run summary per city (read by CRM Settings → Integrations).
LAST_SYNC: dict[str, dict] = {}


def _norm_phone(text: str) -> str:
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


@asynccontextmanager
async def leads_sync_lock(db: AsyncSession, wait_seconds: int = 0):
    """One lead sync at a time across every process (the scheduler in each
    worker, a script run by hand). Two syncs starting together both see a
    lead as missing and both insert it. Yields whether the lock was got;
    a database-wide named lock on MySQL, a no-op elsewhere (tests)."""
    if db.get_bind().dialect.name != "mysql":
        yield True
        return
    from ..db.session import engine
    async with engine.connect() as conn:  # the lock lives on this connection, so it's kept open
        got = (await conn.execute(text("SELECT GET_LOCK('tele_call_leads_sync', :w)"), {"w": wait_seconds})).scalar()
        try:
            yield bool(got)
        finally:
            if got:
                await conn.execute(text("SELECT RELEASE_LOCK('tele_call_leads_sync')"))


async def sync_tele_call_leads(db: AsyncSession, *, locked: bool = False) -> dict:
    """Fetch all TL sheets and upsert leads into DB. Returns summary. Skips
    (status "skipped") when another sync is already running; `locked` means
    the caller already holds leads_sync_lock."""
    if locked:
        return await _sync_tele_call_leads(db)
    async with leads_sync_lock(db) as got:
        if not got:
            logger.info("Lead sync skipped: another one is running")
            return {"status": "skipped", "rows_synced": 0, "crm": {}}
        return await _sync_tele_call_leads(db)


async def _sync_tele_call_leads(db: AsyncSession) -> dict:
    """Fetch all TL sheets and upsert leads into DB. Returns summary.

    Read-only towards Google Sheets. Existing rows are matched on
    spreadsheet + full_name + phone + created_time as before, with a
    fallback on (phone, created_time) so a name corrected in the sheet
    updates the same lead instead of creating a duplicate.
    """
    from .crm.sync_hooks import SyncContext, after_upsert
    from .crm.status import normalize_status
    from .crm.engine import emit_alerts

    total_synced = 0
    ctx = await SyncContext.build(db)

    # Meta leads the webhook already created (not yet tied to a sheet row):
    # the sheet copy of the same lead attaches to them instead of becoming
    # a second lead. Matched on phone + submission time within a day.
    from .crm.meta_leads import MERGE_WINDOW
    from .crm.timeutil import parse_sheet_datetime
    webhook_leads: dict[str, list[TeleCallLead]] = {}
    for row in (await db.execute(select(TeleCallLead).where(
        TeleCallLead.external_ref.like("meta:%"), TeleCallLead.spreadsheet_id == "",
        TeleCallLead.created_at >= datetime.utcnow() - timedelta(days=7),
    ))).scalars().all():
        webhook_leads.setdefault(_norm_phone(row.phone), []).append(row)

    def webhook_twin(phone: str, created_time: str) -> TeleCallLead | None:
        at = parse_sheet_datetime(created_time)
        cands = [r for r in webhook_leads.get(_norm_phone(phone), [])
                 if at and r.submitted_at and abs(r.submitted_at - at) <= MERGE_WINDOW]
        if not cands:
            return None
        twin = min(cands, key=lambda r: abs(r.submitted_at - at))
        webhook_leads[_norm_phone(phone)].remove(twin)
        return twin

    for sheet_cfg in TELE_CALL_SHEETS:
        spreadsheet_id = sheet_key(sheet_cfg)
        tl_name = sheet_cfg["tl_name"]

        try:
            leads = await asyncio.to_thread(_fetch_sheet_rows, sheet_cfg["spreadsheet_id"], sheet_cfg.get("tab"))
        except Exception as e:
            logger.error(f"Failed to fetch tele sheet for {tl_name}: {e}")
            LAST_SYNC[tl_name] = {"at": datetime.now(timezone.utc).isoformat(), "ok": False,
                                  "error": str(e)[:300], "rows": 0}
            continue

        # One query per sheet instead of one per row.
        existing_rows = (await db.execute(
            select(TeleCallLead).where(TeleCallLead.spreadsheet_id == spreadsheet_id)
        )).scalars().all()
        by_key: dict[tuple, TeleCallLead] = {}
        by_phone_time: dict[tuple, TeleCallLead] = {}
        for row in existing_rows:
            by_key[(row.full_name, row.phone, row.created_time)] = row
            ph = _norm_phone(row.phone)
            if ph:
                by_phone_time.setdefault((ph, row.created_time), row)

        synced = 0
        inserted = 0
        for lead_data in leads:
            phone = lead_data.get("phone", "")
            full_name = lead_data.get("full_name", "")
            created_time = lead_data.get("created_time", "")

            existing = by_key.get((full_name, phone, created_time))
            if existing is None:
                ph = _norm_phone(phone)
                candidate = by_phone_time.get((ph, created_time)) if ph else None
                if candidate is not None:
                    # Same Meta lead, name/phone formatting edited in the sheet.
                    by_key.pop((candidate.full_name, candidate.phone, candidate.created_time), None)
                    candidate.full_name = full_name
                    candidate.phone = phone
                    by_key[(full_name, phone, created_time)] = candidate
                    existing = candidate
            if existing is None:
                twin = webhook_twin(phone, created_time)
                if twin is not None:
                    # Same Meta lead the webhook already created: from now on
                    # it is this sheet row (keeps its owner, source and Hot flag).
                    twin.spreadsheet_id = spreadsheet_id
                    twin.full_name, twin.phone, twin.created_time = full_name, phone, created_time
                    by_key[(full_name, phone, created_time)] = twin
                    existing = twin

            raw_status = lead_data.get("status", "")
            fields = {
                "sheet_tl_name": tl_name,
                "person_calling": lead_data.get("person_calling", ""),
                "lead_source": lead_data.get("lead_source", ""),
                "status": normalize_status(raw_status),
                "call_date": lead_data.get("call_date", ""),
                "appointment_date": lead_data.get("appointment_date", ""),
                "remarks": lead_data.get("remarks", ""),
                "sale_amount": lead_data.get("sale_amount", ""),
                "product": lead_data.get("product", ""),
                "last_synced_at": datetime.now(timezone.utc),
            }
            if "bill_no" in lead_data:  # only sheets that have the column
                fields["bill_no"] = lead_data["bill_no"]

            if existing:
                old_status = existing.status or ""
                # Only knowable while the sheet still controls the cell.
                person_changed = (not existing.edited_by_user
                                  and "person_calling" not in (existing.edited_fields or [])
                                  and (existing.person_calling or "") != fields["person_calling"])
                # Fields changed in the app are never overwritten by the sheet.
                protected = set(existing.edited_fields or [])
                for k, v in fields.items():
                    if k == "last_synced_at":
                        setattr(existing, k, v)
                        continue
                    if existing.edited_by_user and k not in SHEET_FIELDS_AFTER_APP_EDIT:
                        continue  # original protection of manual edits
                    if k in protected:
                        continue
                    setattr(existing, k, v)
                existing.sheet_status_raw = raw_status[:100] if raw_status else None
                new_status = existing.status or ""
                await after_upsert(ctx, existing, is_new=False,
                                   sheet_person_calling=fields["person_calling"],
                                   old_status=old_status, status_changed=new_status != old_status,
                                   sheet_person_changed=person_changed)
            else:
                new_lead = TeleCallLead(
                    spreadsheet_id=spreadsheet_id,
                    full_name=full_name,
                    phone=phone,
                    email=lead_data.get("email", ""),
                    created_time=created_time,
                    sheet_status_raw=raw_status[:100] if raw_status else None,
                    source_channel="meta_sheet",
                    created_at=datetime.utcnow(),
                    **fields,
                )
                db.add(new_lead)
                await db.flush()
                by_key[(full_name, phone, created_time)] = new_lead
                ph = _norm_phone(phone)
                if ph:
                    by_phone_time.setdefault((ph, created_time), new_lead)
                await after_upsert(ctx, new_lead, is_new=True,
                                   sheet_person_calling=fields["person_calling"],
                                   old_status="", status_changed=False)
                inserted += 1
            synced += 1

        await db.commit()
        total_synced += synced
        LAST_SYNC[tl_name] = {"at": datetime.now(timezone.utc).isoformat(), "ok": True,
                              "rows": synced, "inserted": inserted, "error": None}
        logger.info(f"Synced tele leads for {tl_name}: {synced} rows ({inserted} new)")

    await db.commit()
    try:  # new leads may match a bill's customer mobile; bill numbers typed in the sheets get checked
        from .crm.bill_verify import run_bill_matching
        matching = await run_bill_matching(db)
        ctx.stats["bills"] = matching["by_bill_no"]
        ctx.stats["bills_by_mobile"] = matching["by_mobile"]
    except Exception as e:
        logger.error(f"Bill verification failed: {e}")
        await db.rollback()
    from .crm.notify import emit_notifications
    await emit_notifications(ctx.new_notifications)  # first, so the browser skips a second popup
    await emit_alerts(ctx.new_alerts)

    try:
        from ..socket import sio
        await sio.emit("data:refresh", {"section": "tele_call_leads"})
    except Exception as e:
        logger.warning(f"Failed to emit socket refresh: {e}")

    return {"status": "ok", "rows_synced": total_synced, "crm": ctx.stats}


async def fetch_tele_leads_direct() -> dict:
    """Fetch all TL sheets directly (no DB) — for live view."""
    await asyncio.to_thread(refresh_sheet_list)
    all_leads = []
    for sheet_cfg in TELE_CALL_SHEETS:
        try:
            leads = await asyncio.to_thread(
                _fetch_sheet_rows, sheet_cfg["spreadsheet_id"], sheet_cfg.get("tab")
            )
            for lead in leads:
                lead["sheet_tl_name"] = sheet_cfg["tl_name"]
                lead["spreadsheet_id"] = sheet_key(sheet_cfg)
            all_leads.extend(leads)
        except Exception as e:
            logger.error(f"Direct fetch failed for {sheet_cfg['tl_name']}: {e}")
    return {"leads": all_leads, "total": len(all_leads)}
