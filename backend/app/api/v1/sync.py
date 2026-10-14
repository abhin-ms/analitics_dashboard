from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from ...core.deps import get_db, require_permission, require_admin_tier
from ...models.models import DailySubmission, SheetSource, SheetSyncLog, StoreWalkin, TeleCallLead, User
from ...schemas import SheetSourceCreate, SheetSourceUpdate, SheetSourceResponse

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/mcp")
async def manual_mcp_sync(
    from_date: str = None,
    to_date: str = None,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("dashboard", "view"),
):
    """Pull the latest sales from MCP (SmartService) for every country,
    including India, and persist them into mcp_daily_sales."""
    from ...services.mcp_sync_service import sync_mcp_sales
    return await sync_mcp_sales(db, from_date, to_date)


@router.post("/insights")
async def manual_insight_run(
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("dashboard", "view"),
):
    """Recompute the CEO Dashboard's auto-detected Action Center insights
    right now, instead of waiting for the next scheduled run."""
    from ...services.insight_engine import generate_auto_insights
    return await generate_auto_insights(db)


@router.get("/mcp/status")
async def mcp_sync_status(
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("dashboard", "view"),
):
    """Last time the MCP sales sync ran, for the dashboard's sync badge."""
    from ...models.models import Setting
    from ...services.mcp_sync_service import LAST_SYNC_SETTING_KEY
    result = await db.execute(select(Setting).where(Setting.key == LAST_SYNC_SETTING_KEY))
    setting = result.scalar_one_or_none()
    return {"last_synced_at": setting.value if setting else None}


async def _daily_tracker_source(db: AsyncSession) -> SheetSource | None:
    """The sheet source holding the Daily Tracker xlsx ("Daily Input" tab)."""
    result = await db.execute(select(SheetSource).where(SheetSource.is_xlsx_upload.is_(True)))
    return next((s for s in result.scalars().all() if "daily_input" in (s.tab_mappings or {})), None)


@router.get("/daily-tracker/status")
async def daily_tracker_sync_status(
    db: AsyncSession = Depends(get_db),
    _user: User = require_admin_tier(),
):
    """Last sync of the Daily Tracker sheet, for the Social Performance page."""
    source = await _daily_tracker_source(db)
    if not source:
        return {"configured": False}
    result = await db.execute(
        select(SheetSyncLog)
        .where(SheetSyncLog.sheet_source_id == source.id)
        .order_by(SheetSyncLog.created_at.desc())
        .limit(1)
    )
    log = result.scalar_one_or_none()
    return {
        "configured": True,
        "enabled": source.is_enabled,
        "interval_minutes": source.sync_interval_minutes,
        "last_synced_at": log.last_synced_at.isoformat() if log and log.last_synced_at else None,
        "last_status": log.status if log else "",
        "rows_synced": log.rows_synced if log else 0,
    }


@router.post("/daily-tracker")
async def daily_tracker_sync(
    db: AsyncSession = Depends(get_db),
    _user: User = require_admin_tier(),
):
    """Re-read the Daily Tracker sheet now instead of waiting for the
    scheduled sync. Open to the same roles that can view the Social
    Performance page, unlike /manual/{id} which needs sheet_sync:edit."""
    source = await _daily_tracker_source(db)
    if not source:
        raise HTTPException(status_code=404, detail="Daily Tracker sheet source is not configured")
    from ...services.sheet_sync_service import SheetSyncService
    return await SheetSyncService().sync_source(db, source.id)


def _utc(dt):
    """Naive-UTC timestamp as an ISO string the browser reads as UTC."""
    if dt is None:
        return None
    return (dt.replace(tzinfo=None).isoformat() + "Z") if hasattr(dt, "tzinfo") else str(dt)


@router.get("/background-sheets")
async def list_background_sheets(
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("sheet_sync", "view"),
):
    """The sheets that sync on their own schedule and aren't "sources" in
    the table above: each team leader's lead sheet (one tab per store), the
    Walk-ins sheet, and the stores' daily form."""
    from ...services.tele_call_sync import LAST_SYNC, TELE_CALL_SHEETS, TL_SPREADSHEETS, sheet_key
    from ...services import daily_submission_sync, walkins_sync

    stats = {k: (n, last) for k, n, last in (await db.execute(
        select(TeleCallLead.spreadsheet_id, func.count(TeleCallLead.id), func.max(TeleCallLead.last_synced_at))
        .group_by(TeleCallLead.spreadsheet_id))).all()}
    lead_sheets = []
    for sp in TL_SPREADSHEETS:
        tabs = []
        for cfg in (c for c in TELE_CALL_SHEETS if c["spreadsheet_id"] == sp["spreadsheet_id"]):
            n, last = stats.get(sheet_key(cfg), (0, None))
            run = LAST_SYNC.get(cfg["tl_name"]) or {}
            tabs.append({"name": cfg["tl_name"], "tab": cfg["tab"], "leads": int(n or 0), "last_synced_at": _utc(last),
                         "ok": run.get("ok", True), "error": run.get("error")})
        times = [t["last_synced_at"] for t in tabs if t["last_synced_at"]]
        lead_sheets.append({
            "team_leader": sp["team_leader"], "spreadsheet_id": sp["spreadsheet_id"], "tabs": tabs,
            "leads": sum(t["leads"] for t in tabs), "last_synced_at": max(times) if times else None,
            "status": "error" if any(not t["ok"] for t in tabs) else "ok" if times else "never",
        })

    w_rows, w_last, w_date = (await db.execute(select(func.count(StoreWalkin.id), func.max(StoreWalkin.synced_at), func.max(StoreWalkin.date)))).one()
    d_rows, d_last, d_date = (await db.execute(
        select(func.count(DailySubmission.id), func.max(DailySubmission.updated_at), func.max(DailySubmission.date))
        .where(DailySubmission.submitted_by.is_(None)))).one()
    other = [
        {"key": "walkins", "label": "Walk-ins Data", "spreadsheet_id": walkins_sync.WALKINS_SHEET_ID, "every": "15 min",
         "rows": int(w_rows or 0), "rows_label": "store-days",
         "last_synced_at": walkins_sync.LAST_SYNC.get("at") or _utc(w_last),  # the last run, else the last row written
         "latest_data": w_date.isoformat() if w_date else None, "status": "ok" if w_rows else "never",
         "unmatched": walkins_sync.LAST_SYNC.get("unmatched_stores") or []},
        {"key": "daily-form", "label": "Stores' daily form (Dashboard Sheet · DAILY SUBMISSION tab)",
         "spreadsheet_id": daily_submission_sync.DASHBOARD_SHEET_ID, "every": "15 min",
         "rows": int(d_rows or 0), "rows_label": "store-days",
         "last_synced_at": daily_submission_sync.LAST_SYNC.get("at") or _utc(d_last),
         "latest_data": d_date.isoformat() if d_date else None, "status": "ok" if d_rows else "never",
         "unmatched": daily_submission_sync.LAST_SYNC.get("unmatched_stores") or []},
    ]
    return {"lead_sheets": lead_sheets, "other": other}


@router.post("/background-sheets/{key}")
async def sync_background_sheet(
    key: str,
    db: AsyncSession = Depends(get_db),
    _user: User = require_admin_tier(),
):
    """Sync one of the background sheets now: "leads", "walkins" or "daily-form"."""
    import asyncio
    if key == "leads":
        from ...services.tele_call_sync import refresh_sheet_list, sync_tele_call_leads
        await asyncio.to_thread(refresh_sheet_list)
        result = await sync_tele_call_leads(db)
        return {"ok": result["status"] != "skipped", "status": result["status"], "rows": result["rows_synced"],
                "message": "Another lead sync is running; it will finish in a moment." if result["status"] == "skipped" else None}
    if key == "walkins":
        from ...services.walkins_sync import sync_walkins
        return {"ok": True, **(await sync_walkins(db))}
    if key == "daily-form":
        from ...services.daily_submission_sync import sync_daily_submissions
        return {"ok": True, **(await sync_daily_submissions(db))}
    raise HTTPException(status_code=404, detail="Unknown sheet")


@router.get("/sources", response_model=list[SheetSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("sheet_sync", "view"),
):
    result = await db.execute(select(SheetSource).order_by(SheetSource.label))
    sources = result.scalars().all()
    out = []
    for s in sources:
        last_log = await db.execute(
            select(SheetSyncLog)
            .where(SheetSyncLog.sheet_source_id == s.id)
            .order_by(SheetSyncLog.created_at.desc())
            .limit(1)
        )
        log = last_log.scalar_one_or_none()
        out.append(SheetSourceResponse(
            id=s.id, label=s.label, spreadsheet_id=s.spreadsheet_id,
            is_xlsx_upload=s.is_xlsx_upload,
            sync_interval_minutes=s.sync_interval_minutes,
            is_enabled=s.is_enabled, tab_mappings=s.tab_mappings or {},
            last_synced_at=log.last_synced_at if log else None,
            last_sync_status=log.status if log else "",
            created_at=s.created_at,
        ))
    return out


@router.post("/sources", response_model=SheetSourceResponse, status_code=201)
async def create_source(
    body: SheetSourceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("sheet_sync", "create"),
):
    src = SheetSource(
        label=body.label, spreadsheet_id=body.spreadsheet_id,
        is_xlsx_upload=body.is_xlsx_upload,
        sync_interval_minutes=body.sync_interval_minutes,
        is_enabled=body.is_enabled, tab_mappings=body.tab_mappings,
        created_by=user.id,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return SheetSourceResponse(
        id=src.id, label=src.label, spreadsheet_id=src.spreadsheet_id,
        is_xlsx_upload=src.is_xlsx_upload,
        sync_interval_minutes=src.sync_interval_minutes,
        is_enabled=src.is_enabled, tab_mappings=src.tab_mappings or {},
        created_at=src.created_at,
    )


@router.put("/sources/{source_id}", response_model=SheetSourceResponse)
async def update_source(
    source_id: int, body: SheetSourceUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("sheet_sync", "edit"),
):
    result = await db.execute(select(SheetSource).where(SheetSource.id == source_id))
    src = result.scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(src, field, value)
    await db.commit()
    await db.refresh(src)
    return SheetSourceResponse(
        id=src.id, label=src.label, spreadsheet_id=src.spreadsheet_id,
        is_xlsx_upload=src.is_xlsx_upload,
        sync_interval_minutes=src.sync_interval_minutes,
        is_enabled=src.is_enabled, tab_mappings=src.tab_mappings or {},
        created_at=src.created_at,
    )


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("sheet_sync", "delete"),
):
    result = await db.execute(select(SheetSource).where(SheetSource.id == source_id))
    src = result.scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    await db.delete(src)
    await db.commit()
    return {"message": "Sheet source deleted"}


@router.post("/manual/{source_id}")
async def manual_sync(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("sheet_sync", "edit"),
):
    from ...services.sheet_sync_service import SheetSyncService
    svc = SheetSyncService()
    result = await svc.sync_source(db, source_id)
    return result
