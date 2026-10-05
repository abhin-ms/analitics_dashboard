"""Social media performance from the Daily Tracker sheet, scoped to the
caller: admin-tier roles see every store, a Team Leader sees the stores they
lead, and store-level accounts (Store Owner, Store Staff, Salesperson…) see
the store(s) they are linked to. Also manages per-store view targets."""
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user, require_permission, ADMIN_TIER_ROLES
from ...models.models import (
    DailyStoreTracker, Role, Setting, SheetSyncLog, SocialViewTarget, Store, User,
)

router = APIRouter(prefix="/social", tags=["social"])

# Platforms that carry a views target, and the tracker column holding their
# achieved views. Instagram's is the influencer-video views column.
PLATFORM_VIEWS = {
    "instagram": "ig_views_achieved",
    "youtube": "yt_views",
    "facebook": "fb_views",
}
DEFAULT_TARGET = 1_000_000
_DEFAULT_KEY = "social_target_default:{}"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def tracker_row_dict(r: DailyStoreTracker) -> dict:
    """One Daily Input row as the dashboards consume it."""
    return {
        "store_id": r.store_id,
        "date": r.date,
        "store": r.store_name,
        "country": r.country,
        "store_type": r.store_type,
        "daily_revenue": float(r.daily_revenue or 0),
        "monthly_target": float(r.monthly_target or 0),
        "mtd_revenue": float(r.mtd_revenue or 0),
        "units_sold": r.units_sold,
        "care_plus_attached": r.care_plus_attached,
        "prebookings": r.prebookings,
        "ig_videos_posted": r.ig_videos_posted,
        "ig_views_target": float(r.ig_views_target or 0),
        "ig_views_achieved": float(r.ig_views_achieved or 0),
        "ig_followers": r.ig_followers,
        "ig_new_followers": r.ig_new_followers,
        "ig_likes": r.ig_likes,
        "ig_comments": r.ig_comments,
        "ig_saves": r.ig_saves,
        "ig_shares": r.ig_shares,
        "ig_reposts": r.ig_reposts,
        "ig_dms_received": r.ig_dms_received,
        "ig_manychat_handled": r.ig_manychat_handled,
        "ig_posts_published": r.ig_posts_published,
        "yt_views": r.yt_views,
        "yt_likes": r.yt_likes,
        "yt_comments": r.yt_comments,
        "tt_views": r.tt_views,
        "tt_likes": r.tt_likes,
        "tt_followers": r.tt_followers,
        "sc_views": r.sc_views,
        "sc_shares": r.sc_shares,
        "fb_views": r.fb_views,
        "wa_chats_received": r.wa_chats_received,
        "wa_walkins_booked": r.wa_walkins_booked,
        "google_rating": r.google_rating,
        "google_new_reviews": r.google_new_reviews,
        "google_review_response": r.google_review_response,
        "sheet_updated_at": _iso_utc(r.sheet_updated_at),
    }


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    # Stored as naive UTC; mark it so browsers convert to local time.
    return dt.isoformat() + "Z" if dt else None


async def _default_targets(db: AsyncSession) -> dict[str, int]:
    keys = [_DEFAULT_KEY.format(p) for p in PLATFORM_VIEWS]
    rows = (await db.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    saved = {s.key: s.value for s in rows}
    out = {}
    for p in PLATFORM_VIEWS:
        try:
            out[p] = int(saved.get(_DEFAULT_KEY.format(p)) or DEFAULT_TARGET)
        except ValueError:
            out[p] = DEFAULT_TARGET
    return out


async def _target_overrides(db: AsyncSession, store_ids: Optional[list[int]] = None) -> dict[int, dict[str, int]]:
    q = select(SocialViewTarget)
    if store_ids is not None:
        q = q.where(SocialViewTarget.store_id.in_(store_ids or [-1]))
    out: dict[int, dict[str, int]] = {}
    for t in (await db.execute(q)).scalars().all():
        out.setdefault(t.store_id, {})[t.platform] = int(t.monthly_target)
    return out


async def social_scope(user: User, db: AsyncSession) -> dict:
    """Which stores this user's social figures cover. store_ids None = all."""
    role = (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none() or ""
    if role in ADMIN_TIER_ROLES:
        return {"kind": "company", "role": role, "store_ids": None}
    if role == "Team Leader":
        ids = (await db.execute(
            select(Store.id).where(Store.team_leader_id == user.id, Store.is_active == True)  # noqa: E712
        )).scalars().all()
        return {"kind": "team_leader", "role": role, "store_ids": list(ids)}
    ids = {sa.store_id for sa in user.store_access}
    if user.store_id:
        ids.add(user.store_id)
    return {"kind": "store", "role": role, "store_ids": sorted(ids)}


@router.get("/performance")
async def social_performance(
    month: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scope = await social_scope(user, db)
    scoped = scope["store_ids"]

    if scoped is None:
        # Company view: every store that has ever appeared in the tracker.
        store_ids = list((await db.execute(select(DailyStoreTracker.store_id).distinct())).scalars().all())
    else:
        store_ids = scoped
    in_scope = DailyStoreTracker.store_id.in_(store_ids or [-1])

    dates = (await db.execute(select(DailyStoreTracker.date).where(in_scope).distinct())).scalars().all()
    months = sorted({d[:7] for d in dates if d and _ISO_DATE.match(d)}, reverse=True)
    if month and not re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    active = month or (months[0] if months else date.today().strftime("%Y-%m"))

    rows = (await db.execute(
        select(DailyStoreTracker)
        .where(in_scope, DailyStoreTracker.date >= f"{active}-01", DailyStoreTracker.date <= f"{active}-31")
        .order_by(DailyStoreTracker.date.desc())
    )).scalars().all()

    # Latest sheet change and latest period covered, per store, across all months.
    last = {
        sid: (upd, per)
        for sid, upd, per in (await db.execute(
            select(DailyStoreTracker.store_id, func.max(DailyStoreTracker.sheet_updated_at),
                   func.max(DailyStoreTracker.date))
            .where(in_scope, DailyStoreTracker.date.like("____-__-__"))
            .group_by(DailyStoreTracker.store_id)
        )).all()
    }
    country = {
        sid: c for sid, c in (await db.execute(
            select(DailyStoreTracker.store_id, DailyStoreTracker.country)
            .where(in_scope).order_by(DailyStoreTracker.date)
        )).all() if c
    }

    stores = (await db.execute(
        select(Store, User.name).outerjoin(User, Store.team_leader_id == User.id)
        .where(Store.id.in_(store_ids or [-1]))
        .order_by(Store.name)
    )).all()
    defaults = await _default_targets(db)
    overrides = await _target_overrides(db, store_ids)

    from .sync import _daily_tracker_source
    source = await _daily_tracker_source(db)
    last_sync = None
    if source:
        last_sync = (await db.execute(
            select(func.max(SheetSyncLog.last_synced_at)).where(SheetSyncLog.sheet_source_id == source.id)
        )).scalar_one_or_none()

    if scope["kind"] == "company":
        label = "All stores"
    elif len(stores) == 1:
        label = stores[0][0].name
    elif scope["kind"] == "team_leader":
        label = f"Your {len(stores)} stores"
    else:
        label = f"{len(stores)} stores"

    return {
        "scope": {"kind": scope["kind"], "label": label, "can_sync": scope["kind"] == "company"},
        "platforms": list(PLATFORM_VIEWS),
        "months": months,
        "month": active,
        "last_synced_at": _iso_utc(last_sync.replace(tzinfo=None) if last_sync else None),
        "stores": [
            {
                "store_id": s.id,
                "store": s.name,
                "country": country.get(s.id) or s.country or "",
                "team_leader": tl_name or "",
                "targets": {p: overrides.get(s.id, {}).get(p, defaults[p]) for p in PLATFORM_VIEWS},
                "last_updated_at": _iso_utc(last.get(s.id, (None, None))[0]),
                "last_period": last.get(s.id, (None, None))[1],
            }
            for s, tl_name in stores
        ],
        "rows": [tracker_row_dict(r) for r in rows],
    }


# ── Targets (admin) ─────────────────────────────────────────────────
@router.get("/targets")
async def get_targets(
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("settings", "view"),
):
    tracker_ids = set((await db.execute(select(DailyStoreTracker.store_id).distinct())).scalars().all())
    stores = (await db.execute(
        select(Store, User.name).outerjoin(User, Store.team_leader_id == User.id)
        .where((Store.is_active == True) | (Store.id.in_(list(tracker_ids) or [-1])))  # noqa: E712
        .order_by(Store.name)
    )).all()
    overrides = await _target_overrides(db)
    return {
        "platforms": list(PLATFORM_VIEWS),
        "defaults": await _default_targets(db),
        "stores": [
            {
                "store_id": s.id,
                "store": s.name,
                "team_leader": tl_name or "",
                "in_tracker": s.id in tracker_ids,
                "overrides": {p: overrides.get(s.id, {}).get(p) for p in PLATFORM_VIEWS},
            }
            for s, tl_name in stores
        ],
    }


class TargetOverride(BaseModel):
    store_id: int
    platform: str
    monthly_target: Optional[int] = Field(default=None, ge=0)  # None = back to default


class TargetsUpdate(BaseModel):
    defaults: Optional[dict[str, int]] = None
    overrides: list[TargetOverride] = []


@router.put("/targets")
async def update_targets(
    body: TargetsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("settings", "edit"),
):
    for p, v in (body.defaults or {}).items():
        if p not in PLATFORM_VIEWS or v < 0:
            raise HTTPException(status_code=400, detail=f"Invalid default target for {p}")
        key = _DEFAULT_KEY.format(p)
        setting = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        if setting:
            setting.value, setting.updated_by = str(v), user.id
        else:
            db.add(Setting(key=key, value=str(v), updated_by=user.id))

    for o in body.overrides:
        if o.platform not in PLATFORM_VIEWS:
            raise HTTPException(status_code=400, detail=f"Unknown platform {o.platform}")
        if o.monthly_target is None:
            await db.execute(delete(SocialViewTarget).where(
                SocialViewTarget.store_id == o.store_id, SocialViewTarget.platform == o.platform))
            continue
        row = (await db.execute(select(SocialViewTarget).where(
            SocialViewTarget.store_id == o.store_id, SocialViewTarget.platform == o.platform,
        ))).scalar_one_or_none()
        if row:
            row.monthly_target, row.updated_by = o.monthly_target, user.id
        else:
            db.add(SocialViewTarget(store_id=o.store_id, platform=o.platform,
                                    monthly_target=o.monthly_target, updated_by=user.id))
    await db.commit()
    return {"ok": True}
