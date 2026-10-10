import asyncio
import hashlib
import json
import logging
from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from ..models.models import (
    SheetSource, SheetSyncLog, DailySubmission, Store, User, Role,
    StoreStaff, InternationalStore, GoogleReview, StrategicInsight,
    DailyStoreTracker, StoreDashboardSnapshot, StoreMcpAlias,
)
import secrets
from ..core.security import hash_password

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))
CURRENT_MONTH = datetime.now().strftime("%Y-%m")
TODAY = date.today()


def parse_ops_date(text: str) -> Optional[date]:
    """The Operations sheet's "Date" column. It is a Google Form, so dates
    are US-style M/D/YYYY (7/14/2026); reading them as D/M put 12 July on
    7 December and dropped every day above 12."""
    text = (text or "").strip().split(" ")[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class SheetSyncService:
    async def sync_source(self, db: AsyncSession, source_id: int) -> dict:
        result = await db.execute(select(SheetSource).where(SheetSource.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return {"status": "error", "message": "Source not found"}

        if not source.is_enabled:
            return {"status": "skipped", "message": "Source is disabled"}

        try:
            if source.is_xlsx_upload:
                return await self._sync_xlsx(db, source)
            return await self._sync_with_gsheets(db, source)
        except Exception as e:
            logger.error(f"Sync failed for source {source_id}: {e}", exc_info=True)
            log = SheetSyncLog(
                sheet_source_id=source_id, tab_name="",
                last_synced_at=datetime.now(timezone.utc),
                rows_synced=0, status="error",
                error_message=str(e),
            )
            db.add(log)
            await db.commit()
            return {"status": "error", "message": str(e)}

    async def _sync_with_gsheets(self, db: AsyncSession, source) -> dict:
        from ..services.google_sheets import (
            fetch_ops_data, fetch_store_config, fetch_store_config_v2,
            fetch_osmc_staff, fetch_intl_staff, fetch_google_reviews,
            fetch_gr_action_plan,
        )

        total_rows = 0
        tab = source.tab_mappings or {}
        source_id = source.id
        tab_map = dict(tab) if tab else {}
        tl_role = await self._get_or_create_role(db, "Team Leader")

        if "ops_data" in tab:
            try:
                rows = await asyncio.to_thread(fetch_ops_data)
                for r in rows:
                    tl_name = r.get("tl", "")
                    store_name = r.get("store", "")
                    if not store_name:
                        continue
                    user = await self._get_or_create_tl(db, tl_name, tl_role.id)
                    store = await self._get_or_create_store(db, store_name, user.id)
                    await self._upsert_submission(db, store.id, r)
                    total_rows += 1
                await db.commit()
                logger.info(f"Synced ops_data: {total_rows} rows")
            except Exception as e:
                logger.error(f"ops_data sync error: {e}")
                await db.rollback()

        config_rows = 0
        if "store_config" in tab:
            try:
                rows = await asyncio.to_thread(fetch_store_config)
                for r in rows:
                    tl_name = r.get("tl", "")
                    store_name = r.get("store", "")
                    if not store_name:
                        continue
                    user = await self._get_or_create_tl(db, tl_name, tl_role.id)
                    store = await self._get_or_create_store(db, store_name, user.id)
                    if r.get("monthly_target") is not None and not await self._is_mcp_managed_target(db, store.id):
                        store.monthly_target = r["monthly_target"]
                    if r.get("breakeven_rev") is not None:
                        store.breakeven_revenue = r["breakeven_rev"]
                    if r.get("profitability_target") is not None:
                        store.profitability_target = r["profitability_target"]
                    if r.get("fixed_costs") is not None:
                        store.fixed_costs = r["fixed_costs"]
                    config_rows += 1
                await db.commit()
                total_rows += config_rows
                logger.info(f"Synced store_config: {config_rows} rows")
            except Exception as e:
                logger.error(f"store_config sync error: {e}")
                await db.rollback()

        if "store_config_v2" in tab:
            try:
                rows = await asyncio.to_thread(fetch_store_config_v2)
                v2_rows = 0
                for r in rows:
                    store_name = r.get("store", "")
                    if not store_name:
                        continue
                    result = await db.execute(
                        select(Store).where(Store.name == store_name)
                    )
                    store = result.scalar_one_or_none()
                    if store:
                        if r.get("daily_target") is not None:
                            store.daily_target = r["daily_target"]
                        if r.get("monthly_target") is not None and not await self._is_mcp_managed_target(db, store.id):
                            store.monthly_target = r["monthly_target"]
                        v2_rows += 1
                await db.commit()
                total_rows += v2_rows
                logger.info(f"Synced store_config_v2: {v2_rows} rows")
            except Exception as e:
                logger.error(f"store_config_v2 sync error: {e}")
                await db.rollback()

        if "staff" in tab:
            try:
                rows = await asyncio.to_thread(fetch_osmc_staff)
                staff_rows = 0
                for r in rows:
                    store_name = r.get("store", "")
                    if not store_name:
                        continue
                    result = await db.execute(
                        select(Store).where(Store.name == store_name)
                    )
                    store = result.scalar_one_or_none()
                    if not store:
                        continue
                    existing = await db.execute(
                        select(StoreStaff).where(
                            and_(
                                StoreStaff.store_id == store.id,
                                StoreStaff.month == CURRENT_MONTH,
                            )
                        )
                    )
                    ss = existing.scalar_one_or_none()
                    if ss:
                        ss.manager_name = r.get("manager", ss.manager_name)
                        ss.staff_count = r.get("staff_count", ss.staff_count)
                        ss.has_accommodation = r.get("has_accommodation", ss.has_accommodation)
                        ss.training_active = r.get("training", ss.training_active)
                        ss.notes = r.get("notes", ss.notes)
                    else:
                        ss = StoreStaff(
                            store_id=store.id,
                            month=CURRENT_MONTH,
                            manager_name=r.get("manager", ""),
                            staff_count=r.get("staff_count", 0),
                            has_accommodation=r.get("has_accommodation", False),
                            training_active=r.get("training", False),
                            notes=r.get("notes", ""),
                        )
                        db.add(ss)
                    staff_rows += 1
                await db.commit()
                total_rows += staff_rows
                logger.info(f"Synced staff: {staff_rows} rows")
            except Exception as e:
                logger.error(f"staff sync error: {e}")
                await db.rollback()

        if "intl_staff" in tab:
            try:
                rows = await asyncio.to_thread(fetch_intl_staff)
                intl_rows = 0
                for r in rows:
                    store_name = r.get("store", "")
                    if not store_name:
                        continue
                    existing = await db.execute(
                        select(InternationalStore).where(
                            and_(
                                InternationalStore.name == store_name,
                                InternationalStore.month == CURRENT_MONTH,
                            )
                        )
                    )
                    istore = existing.scalar_one_or_none()
                    if istore:
                        istore.actual = r.get("total", istore.actual)
                        istore.target = r.get("target", istore.target)
                    else:
                        country = "UAE"
                        region = "AUH"
                        if "oman" in store_name.lower():
                            country = "Oman"
                            region = "OMN"
                        istore = InternationalStore(
                            name=store_name,
                            country=country,
                            region=region,
                            month=CURRENT_MONTH,
                            target=r.get("target"),
                            actual=r.get("total", 0),
                        )
                        db.add(istore)
                    intl_rows += 1
                await db.commit()
                total_rows += intl_rows
                logger.info(f"Synced intl_staff: {intl_rows} rows")
            except Exception as e:
                logger.error(f"intl_staff sync error: {e}")
                await db.rollback()

        if "reviews" in tab:
            try:
                rows = await asyncio.to_thread(fetch_google_reviews)
                review_rows = 0
                for r in rows:
                    store_name = r.get("store", "")
                    if not store_name:
                        continue
                    result = await db.execute(
                        select(Store).where(Store.name == store_name)
                    )
                    store = result.scalar_one_or_none()
                    if not store:
                        continue
                    existing = await db.execute(
                        select(GoogleReview).where(
                            and_(
                                GoogleReview.store_id == store.id,
                                GoogleReview.date == TODAY,
                            )
                        )
                    )
                    gr = existing.scalar_one_or_none()
                    if gr:
                        gr.rating = r.get("current_rating", gr.rating)
                        gr.total_reviews = r.get("current_total_reviews", gr.total_reviews)
                        gr.new_reviews = r.get("new_reviews", gr.new_reviews)
                    else:
                        gr = GoogleReview(
                            store_id=store.id,
                            date=TODAY,
                            rating=r.get("current_rating", 0),
                            total_reviews=r.get("current_total_reviews", 0),
                            new_reviews=r.get("new_reviews", 0),
                        )
                        db.add(gr)
                    review_rows += 1
                await db.commit()
                total_rows += review_rows
                logger.info(f"Synced reviews: {review_rows} rows")
            except Exception as e:
                logger.error(f"reviews sync error: {e}")
                await db.rollback()

        if "gr_action_plan" in tab:
            try:
                rows = await asyncio.to_thread(fetch_gr_action_plan)
                insight_rows = 0
                for r in rows:
                    store_name = r.get("store", "")
                    if not store_name:
                        continue
                    title = f"GR Action: {store_name}"
                    existing = await db.execute(
                        select(StrategicInsight).where(
                            and_(
                                StrategicInsight.title == title,
                                StrategicInsight.month == CURRENT_MONTH,
                            )
                        )
                    )
                    si = existing.scalar_one_or_none()
                    tier = r.get("tier", "").lower()
                    category = "warning"
                    if "critical" in tier:
                        category = "critical"
                    elif "good" in tier or "star" in tier:
                        category = "good"

                    desc_parts = []
                    if r.get("current_rating"):
                        desc_parts.append(f"Rating: {r['current_rating']}")
                    if r.get("reviews_needed"):
                        desc_parts.append(f"Need {r['reviews_needed']} reviews")
                    if r.get("root_cause"):
                        desc_parts.append(f"Cause: {r['root_cause']}")

                    if si:
                        si.category = category
                        si.description = " | ".join(desc_parts)
                        si.action_tag = r.get("actions", si.action_tag)
                    else:
                        si = StrategicInsight(
                            month=CURRENT_MONTH,
                            category=category,
                            title=title,
                            description=" | ".join(desc_parts),
                            action_tag=r.get("actions", ""),
                            assigned_to=r.get("checklist", ""),
                            section="reviews",
                            priority="critical" if category == "critical" else "high",
                            sort_order=insight_rows,
                        )
                        db.add(si)
                    insight_rows += 1
                await db.commit()
                total_rows += insight_rows
                logger.info(f"Synced gr_action_plan: {insight_rows} rows")
            except Exception as e:
                logger.error(f"gr_action_plan sync error: {e}")
                await db.rollback()

        now = datetime.now(timezone.utc)
        for tab_name in tab_map.values():
            log = SheetSyncLog(
                sheet_source_id=source_id, tab_name=tab_name,
                last_synced_at=now, rows_synced=total_rows,
                status="ok",
            )
            db.add(log)
        await db.commit()

        try:
            from ..socket import sio
            await sio.emit("data:refresh", {
                "source_id": source_id,
                "synced_at": now.isoformat(),
                "rows_synced": total_rows,
            })
        except Exception as e:
            logger.warning(f"Socket emit failed: {e}")

        return {"status": "ok", "rows_synced": total_rows}

    async def _get_or_create_role(self, db: AsyncSession, name: str) -> Role:
        result = await db.execute(select(Role).where(Role.name == name))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(name=name, description=f"{name} role")
            db.add(role)
            await db.flush()
        return role

    async def _get_or_create_tl(self, db: AsyncSession, tl_name: str, role_id: int) -> User:
        if not tl_name:
            tl_name = "Unassigned"
        result = await db.execute(
            select(User).where(User.name.ilike(tl_name))
        )
        user = result.scalar_one_or_none()
        if not user:
            email = f"{tl_name.lower().replace(' ', '.')}@system.local"
            existing_email = await db.execute(
                select(User).where(User.email == email)
            )
            user = existing_email.scalar_one_or_none()
            if not user:
                user = User(
                    name=tl_name,
                    email=email,
                    password_hash=DEFAULT_PASSWORD_HASH,
                    role_id=role_id,
                    is_active=False,
                )
                db.add(user)
                await db.flush()
        return user

    async def _is_mcp_managed_target(self, db: AsyncSession, store_id: int) -> bool:
        """True once a store has any MCP alias — meaning the automatic MCP
        sync (every 15 min, see mcp_sync_service.sync_mcp_sales) is already
        keeping its monthly_target current from MCP's own live target
        sheet. Letting this Sheets sync also write monthly_target for such
        a store created a race: this sync runs every 1 minute vs MCP's 15,
        so a stale/unmaintained manual figure in the Sheet would overwrite
        the correct MCP-derived target within a minute of every correction,
        making the dashboard's target look "randomly wrong again" days
        after it had been fixed. monthly_target now has exactly one
        authoritative source per store — MCP once aliased, this Sheet only
        for the store's other fields and for stores MCP doesn't track."""
        return (await db.execute(
            select(StoreMcpAlias.id).where(StoreMcpAlias.store_id == store_id).limit(1)
        )).scalar_one_or_none() is not None

    async def _get_or_create_store(self, db: AsyncSession, name: str, tl_user_id: int) -> Store:
        result = await db.execute(select(Store).where(Store.name == name))
        store = result.scalar_one_or_none()
        if not store:
            # This exact name may belong to a branch that was already
            # merged/renamed away (its Store row deleted) — without this
            # check, that merge gets silently undone the next time this
            # sheet is synced, since a fresh row would otherwise be created
            # here under the same retired name every time. See
            # store_merge_service.merge_store_into, which records every
            # merged branch's name here permanently before deleting it.
            alias = (await db.execute(
                select(StoreMcpAlias).where(StoreMcpAlias.mcp_shop_name == name)
            )).scalar_one_or_none()
            if alias:
                aliased_store = (await db.execute(
                    select(Store).where(Store.id == alias.store_id)
                )).scalar_one_or_none()
                if aliased_store:
                    return aliased_store
        if not store:
            store = Store(
                name=name,
                team_leader_id=tl_user_id,
                currency_code="INR",
                is_active=True,
            )
            db.add(store)
            await db.flush()
        elif store.team_leader_id != tl_user_id:
            store.team_leader_id = tl_user_id
        return store

    async def _upsert_submission(self, db: AsyncSession, store_id: int, row: dict) -> None:
        sub_date = parse_ops_date(row.get("date", ""))
        if not sub_date:
            return

        result = await db.execute(
            select(DailySubmission).where(
                and_(DailySubmission.store_id == store_id, DailySubmission.date == sub_date)
            )
        )
        sub = result.scalar_one_or_none()

        data = {
            "revenue": row.get("revenue") or 0,
            "units_sold": row.get("units_sold") or 0,
            "new_leads": row.get("new_leads") or 0,
            "active_leads": row.get("active_leads") or 0,
            "calls_made": row.get("calls_made") or 0,
            "calls_connected": row.get("calls_connected") or 0,
            "walk_ins": row.get("walk_ins") or 0,
            "walk_in_conversions": row.get("walk_in_conversions") or 0,
            "care_plus_attached": row.get("care_attached") or 0,
        }

        if sub:
            # The Dashboard Sheet's DAILY SUBMISSION tab (daily_submission_sync)
            # is the store form now; this older log only fills days it lacks.
            return
        sub = DailySubmission(store_id=store_id, date=sub_date, **data)
        db.add(sub)

    async def _sync_xlsx(self, db: AsyncSession, source) -> dict:
        from ..services.xlsx_reader import (
            download_xlsx, parse_daily_input_buf, parse_store_dashboard_buf,
        )

        source_id = source.id
        spreadsheet_id = source.spreadsheet_id
        total_rows = 0

        try:
            buf = await asyncio.to_thread(download_xlsx, spreadsheet_id)
        except Exception as e:
            logger.error(f"xlsx download error: {e}", exc_info=True)
            raise

        daily_ok = False
        try:
            daily_rows = await asyncio.to_thread(parse_daily_input_buf, buf)
            for r in daily_rows:
                store_name = r.get("store", "")
                if not store_name:
                    continue

                result = await db.execute(select(Store).where(Store.name == store_name))
                store = result.scalar_one_or_none()
                if not store:
                    tl_role = await self._get_or_create_role(db, "Team Leader")
                    user = await self._get_or_create_tl(db, "Unassigned", tl_role.id)
                    store = await self._get_or_create_store(db, store_name, user.id)

                existing = await db.execute(
                    select(DailyStoreTracker).where(
                        and_(
                            DailyStoreTracker.store_id == store.id,
                            DailyStoreTracker.date == r.get("date", ""),
                        )
                    )
                )
                tracker = existing.scalar_one_or_none()

                fields = {
                    "store_name": store_name,
                    "country": r.get("country", ""),
                    "store_type": r.get("store_type", ""),
                    "daily_revenue": r.get("daily_revenue") or 0,
                    "monthly_target": r.get("monthly_target") or 0,
                    "mtd_revenue": r.get("mtd_revenue") or 0,
                    "units_sold": r.get("units_sold") or 0,
                    "care_plus_attached": r.get("care_plus_attached") or 0,
                    "prebookings": r.get("prebookings") or 0,
                    "ig_videos_posted": r.get("ig_videos_posted") or 0,
                    "ig_views_target": r.get("ig_views_target") or 0,
                    "ig_views_achieved": r.get("ig_views_achieved") or 0,
                    "ig_views_achd_pct": r.get("ig_views_achd_pct") or 0,
                    "ig_followers": r.get("ig_followers") or 0,
                    "ig_new_followers": r.get("ig_new_followers") or 0,
                    "ig_likes": r.get("ig_likes") or 0,
                    "ig_comments": r.get("ig_comments") or 0,
                    "ig_saves": r.get("ig_saves") or 0,
                    "ig_shares": r.get("ig_shares") or 0,
                    "ig_reposts": r.get("ig_reposts") or 0,
                    "ig_dms_received": r.get("ig_dms_received") or 0,
                    "ig_manychat_handled": r.get("ig_manychat_handled") or 0,
                    "ig_posts_published": r.get("ig_posts_published") or 0,
                    "yt_views": r.get("yt_views") or 0,
                    "yt_likes": r.get("yt_likes") or 0,
                    "yt_comments": r.get("yt_comments") or 0,
                    "tt_views": r.get("tt_views") or 0,
                    "tt_likes": r.get("tt_likes") or 0,
                    "tt_followers": r.get("tt_followers") or 0,
                    "sc_views": r.get("sc_views") or 0,
                    "sc_shares": r.get("sc_shares") or 0,
                    "fb_views": r.get("fb_views") or 0,
                    "wa_chats_received": r.get("wa_chats_received") or 0,
                    "wa_walkins_booked": r.get("wa_walkins_booked") or 0,
                    "google_rating": r.get("google_rating"),
                    "google_new_reviews": r.get("google_new_reviews") or 0,
                    "google_review_response": r.get("google_review_response", ""),
                    "extra_fields": r.get("extra") or None,
                }

                # Fingerprint the row as the sheet has it, so a store's
                # "last updated in sheet" time moves only when its figures
                # actually change — not on every scheduled re-sync.
                row_hash = hashlib.sha256(
                    json.dumps(r, sort_keys=True, default=str).encode()
                ).hexdigest()
                if tracker:
                    for k, v in fields.items():
                        setattr(tracker, k, v)
                    if tracker.row_hash != row_hash:
                        # A pre-tracking row (no hash yet) keeps its back-filled time.
                        if tracker.row_hash is not None or tracker.sheet_updated_at is None:
                            tracker.sheet_updated_at = datetime.utcnow()
                        tracker.row_hash = row_hash
                else:
                    tracker = DailyStoreTracker(
                        store_id=store.id, date=r.get("date", ""), row_hash=row_hash,
                        sheet_updated_at=datetime.utcnow(), **fields,
                    )
                    db.add(tracker)
                total_rows += 1

            await db.commit()
            logger.info(f"Synced xlsx daily_input: {total_rows} rows")
            daily_ok = True
        except Exception as e:
            logger.error(f"xlsx daily_input sync error: {e}", exc_info=True)
            await db.rollback()

        dashboard_rows = 0
        dash_ok = False
        try:
            dash_rows = await asyncio.to_thread(parse_store_dashboard_buf, buf)
            for r in dash_rows:
                store_name = r.get("store", "")
                if not store_name:
                    continue
                result = await db.execute(select(Store).where(Store.name == store_name))
                store = result.scalar_one_or_none()
                if not store:
                    continue

                existing = await db.execute(
                    select(StoreDashboardSnapshot).where(
                        and_(
                            StoreDashboardSnapshot.store_id == store.id,
                            StoreDashboardSnapshot.snapshot_date == datetime.now().strftime("%Y-%m-%d"),
                        )
                    )
                )
                snap = existing.scalar_one_or_none()

                snap_fields = {
                    "store_name": store_name,
                    "country": r.get("country", ""),
                    "mtd_revenue": r.get("mtd_revenue") or 0,
                    "monthly_target": r.get("monthly_target") or 0,
                    "target_pct": r.get("target_pct") or 0,
                    "care_plus_pct": r.get("care_plus_pct") or 0,
                    "total_views": r.get("total_views") or 0,
                    "engagements": r.get("engagements") or 0,
                    "eng_rate_pct": r.get("eng_rate_pct") or 0,
                    "prebookings": r.get("prebookings") or 0,
                    "dms_received": r.get("dms_received") or 0,
                    "wa_response_pct": r.get("wa_response_pct") or 0,
                    "walkins_booked": r.get("walkins_booked") or 0,
                    "insta_followers": r.get("insta_followers") or 0,
                    "follower_growth": r.get("follower_growth") or 0,
                    "google_rating": r.get("google_rating"),
                    "new_reviews": r.get("new_reviews") or 0,
                    "sales_status": r.get("sales_status", ""),
                    "marketing_status": r.get("marketing_status", ""),
                }

                if snap:
                    for k, v in snap_fields.items():
                        setattr(snap, k, v)
                else:
                    snap = StoreDashboardSnapshot(
                        store_id=store.id,
                        snapshot_date=datetime.now().strftime("%Y-%m-%d"),
                        **snap_fields,
                    )
                    db.add(snap)
                dashboard_rows += 1

            await db.commit()
            total_rows += dashboard_rows
            logger.info(f"Synced xlsx store_dashboard: {dashboard_rows} rows")
            dash_ok = True
        except Exception as e:
            logger.error(f"xlsx store_dashboard sync error: {e}", exc_info=True)
            await db.rollback()

        sync_ok = daily_ok and dash_ok
        now = datetime.now(timezone.utc)
        log = SheetSyncLog(
            sheet_source_id=source_id, tab_name="xlsx_all",
            last_synced_at=now, rows_synced=total_rows,
            status="ok" if sync_ok else "error",
            error_message=None if sync_ok else "One or more xlsx tabs failed to sync",
        )
        db.add(log)
        await db.commit()

        try:
            from ..socket import sio
            await sio.emit("data:refresh", {
                "source_id": source_id,
                "synced_at": now.isoformat(),
                "rows_synced": total_rows,
            })
        except Exception as e:
            logger.warning(f"Socket emit failed: {e}")

        return {"status": "ok" if sync_ok else "error", "rows_synced": total_rows}
