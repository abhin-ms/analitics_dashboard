"""Fetch tele call leads from the TL Google Sheets and sync to DB."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.models import TeleCallLead
from .google_sheets import _get_service, _read

logger = logging.getLogger(__name__)

# TL lead sheets — all have identical column structure:
# Lead Source | Created Time | Full Name | Phone number | Email |
# Person Calling | Status | Call date | Appointment Date | Remarks | Sale Amount | Product
# "tab" picks one tab of a spreadsheet that holds several cities; without it
# the first tab is read.
TELE_CALL_SHEETS = [
    {"spreadsheet_id": "1TRA3RXhnXwIsvduSVJddsDprKcmmkUh6zuSrPQMsvAo", "tl_name": "Kerala"},
    {"spreadsheet_id": "1Or2WJUUn_rsb3MKfRE83UJZYgQDiMA-CDvMJLtFCN10", "tl_name": "Guwahati"},
    {"spreadsheet_id": "1SE8tGQgtEDz5Wo3jb1U9fsXzujD3GdKwYy01gRV2rQU", "tl_name": "Bangalore"},
    {"spreadsheet_id": "1jR035-uTOEcshHGM4BBOFyMdPWhbGNlq9o19x3PhFlI", "tl_name": "Delhi"},
    {"spreadsheet_id": "1viO0nNPq-SDJXB29xM32AULi4qoK7PFKMQe4pW3HD4A", "tl_name": "Chennai"},
    # "Dev Leads Tracker": one tab per city ("... Follow up" tabs are formula
    # views of these and are not synced).
    {"spreadsheet_id": "16hQmLFME-ZA2OiIzbt8HmV2o8OTB4J3aKrs4U8GpH0s", "tab": "Mysore", "tl_name": "Mysore"},
    {"spreadsheet_id": "16hQmLFME-ZA2OiIzbt8HmV2o8OTB4J3aKrs4U8GpH0s", "tab": "Mangalore", "tl_name": "Mangalore"},
]


def sheet_key(cfg: dict) -> str:
    """Value stored in TeleCallLead.spreadsheet_id for rows of this sheet.
    Tabs of one spreadsheet get their own key so their leads never match
    each other during sync."""
    return f"{cfg['spreadsheet_id']}#{cfg['tab']}" if cfg.get("tab") else cfg["spreadsheet_id"]

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


def _fetch_sheet_rows(spreadsheet_id: str, tab: str | None = None) -> list[dict]:
    """Fetch all rows from a single TL lead sheet (or one tab of it)."""
    service = _get_service()
    if tab:
        rows = _read(service, spreadsheet_id, f"'{tab}'!A1:L5000")
    else:
        try:
            rows = _read(service, spreadsheet_id, "Sheet1!A1:L5000")
        except Exception as e:
            logger.warning(f"Default tab read failed for {spreadsheet_id}, trying first visible tab: {e}")
            # Some sheets may have different tab names — try first visible tab
            meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheets = meta.get("sheets", [])
            if not sheets:
                return []
            tab_name = sheets[0]["properties"]["title"]
            rows = _read(service, spreadsheet_id, f"{tab_name}!A1:L5000")

    if len(rows) < 2:
        return []

    leads = []
    for row in rows[1:]:
        if not row or not any(cell.strip() for cell in row if cell):
            continue
        record = {}
        for col_idx, field in COL_MAP.items():
            record[field] = row[col_idx].strip() if col_idx < len(row) and row[col_idx] else ""
        # Skip rows with no name at all
        if not record.get("full_name"):
            continue
        leads.append(record)
    return leads


# Sheet fields the sync writes. When a lead was edited in the app
# (edited_by_user) the original behaviour is kept: only these three still
# follow the sheet...
SHEET_FIELDS_AFTER_APP_EDIT = {"lead_source", "product", "sale_amount"}

# Last run summary per city (read by CRM Settings → Integrations).
LAST_SYNC: dict[str, dict] = {}


def _norm_phone(text: str) -> str:
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


async def sync_tele_call_leads(db: AsyncSession) -> dict:
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
