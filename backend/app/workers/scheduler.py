import logging
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from ..services.sheet_sync_service import SheetSyncService

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def sync_all_sources():
    from ..db.session import AsyncSessionLocal
    from sqlalchemy import select, func
    from ..models.models import SheetSource, SheetSyncLog

    svc = SheetSyncService()
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SheetSource).where(SheetSource.is_enabled == True))
        sources = result.scalars().all()

        due = []
        for src in sources:
            interval = src.sync_interval_minutes or 5
            last_q = await db.execute(
                select(func.max(SheetSyncLog.last_synced_at)).where(
                    SheetSyncLog.sheet_source_id == src.id
                )
            )
            last = last_q.scalar()
            if last is not None:
                if last.tzinfo is not None:
                    last = last.replace(tzinfo=None)
                if (now - last).total_seconds() < interval * 60:
                    continue
            due.append(src.id)

    for sid in due:
        logger.info(f"Syncing source: {sid}")
        async with AsyncSessionLocal() as db:
            await svc.sync_source(db, sid)


async def poll_instagram_comments():
    from ..db.session import AsyncSessionLocal
    from ..instagram.bot_engine import poll_and_process_comments

    try:
        async with AsyncSessionLocal() as db:
            await poll_and_process_comments(db)
            await db.commit()
    except Exception as e:
        logger.error("Instagram comment polling error: %s", e)


async def sync_tele_call_leads():
    from ..db.session import AsyncSessionLocal
    from ..services.tele_call_sync import sync_tele_call_leads as _sync

    try:
        async with AsyncSessionLocal() as db:
            await _sync(db)
    except Exception as e:
        logger.error("Tele call leads sync error: %s", e)


async def crm_automation_tick():
    # Telecalling CRM: first-call SLA (5/15/60 min), overdue follow-up
    # routing and alert clean-up — see app/services/crm/automation.py.
    from ..db.session import AsyncSessionLocal
    from ..services.crm.automation import run_automation_tick

    try:
        async with AsyncSessionLocal() as db:
            await run_automation_tick(db)
    except Exception as e:
        logger.error("CRM automation tick error: %s", e)


async def crm_weekly_notifications():
    from ..db.session import AsyncSessionLocal
    from ..services.crm.automation import generate_weekly_notifications

    try:
        async with AsyncSessionLocal() as db:
            count = await generate_weekly_notifications(db)
            logger.info("CRM weekly performance notifications created: %s", count)
    except Exception as e:
        logger.error("CRM weekly notifications error: %s", e)


async def sync_mcp():
    # Keeps mcp_daily_sales and every store's monthly_target fresh from MCP
    # automatically, independent of anyone clicking "Sync Now" — that manual
    # button still exists for an on-demand refresh, but relying on it alone
    # let the DB silently drift out of date (stale targets, revenue) for as
    # long as nobody happened to click it. The dashboard still only ever
    # reads from the DB, never calling MCP live on page load, so this keeps
    # the fast-load design while removing the staleness risk.
    from ..db.session import AsyncSessionLocal
    from ..services.mcp_sync_service import sync_mcp_sales

    try:
        async with AsyncSessionLocal() as db:
            await sync_mcp_sales(db)
    except Exception as e:
        logger.error("MCP sales sync error: %s", e)


async def run_insight_engine():
    # Recomputes the CEO Dashboard's Action Center insights from real data
    # (revenue pace vs target, week-over-week drops, funnel-rate drops) —
    # see app/services/insight_engine.py. Runs on its own schedule rather
    # than piggybacking on sync_mcp/sync_all_sources, since it only needs
    # whatever data is already in the DB at the time, from either pipeline.
    from ..db.session import AsyncSessionLocal
    from ..services.insight_engine import generate_auto_insights

    try:
        async with AsyncSessionLocal() as db:
            await generate_auto_insights(db)
    except Exception as e:
        logger.error("Insight engine error: %s", e)


def start_scheduler():
    if os.getenv("ENABLE_SCHEDULER", "1") != "1":
        logger.info("Scheduler disabled via ENABLE_SCHEDULER=0")
        return

    scheduler.add_job(
        sync_all_sources,
        "interval",
        minutes=1,
        id="sheet_sync_all",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        poll_instagram_comments,
        "interval",
        minutes=15,
        id="instagram_comment_poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    # Every minute (was 5): the telecalling first-call target is 5 minutes,
    # so a new Meta lead must reach the app well inside that window. That is
    # 5 sheet reads a minute — far inside the Google Sheets API quota.
    scheduler.add_job(
        sync_tele_call_leads,
        "interval",
        minutes=1,
        id="tele_call_leads_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        sync_mcp,
        "interval",
        minutes=15,
        id="mcp_sales_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
        # Without this, APScheduler's first run is 15 minutes AFTER the
        # process starts, not immediately — meaning every deploy/migration
        # (which restarts the backend) left a guaranteed window where the
        # dashboard kept showing whatever was synced before that restart,
        # looking like data had "gone wrong" again for no reason. Running
        # once immediately on every startup closes that window permanently.
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        run_insight_engine,
        "interval",
        minutes=30,
        id="insight_engine",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        crm_automation_tick,
        "interval",
        minutes=1,
        id="crm_automation_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        crm_weekly_notifications,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        timezone="Asia/Kolkata",
        id="crm_weekly_notifications",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Scheduler started (sheet sync: 1min, tele call: 1min, CRM automation: 1min, "
                "Instagram poll: 15min, MCP sync: 15min, insight engine: 30min, CRM weekly: Mon 09:00 IST)")
