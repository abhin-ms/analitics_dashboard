"""CRM settings, stored as JSON in the existing key/value `settings` table
(keys prefixed "crm."), merged over these defaults."""
from __future__ import annotations

import copy
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import Setting
from .timeutil import DEFAULT_WORKING_HOURS, utcnow

AUTOMATION_KEY = "crm.automation"
TARGETS_KEY = "crm.targets"
ALIASES_KEY = "crm.name_aliases"
GO_LIVE_KEY = "crm.go_live_at"

DEFAULT_AUTOMATION: dict = {
    "enabled": True,
    "auto_assign": True,
    "working_hours": dict(DEFAULT_WORKING_HOURS),
    # First contact for new Meta leads (working minutes from CRM receipt)
    "first_call_minutes": 5,      # first-call task due / owner alerted + urgent
    "reassign_minutes": 15,       # reassign once to another available agent
    "escalate_minutes": 60,       # escalate to team leader
    # After the first attempt
    "no_answer_retry_minutes": 210,   # 3½ hours
    "busy_retry_minutes": 45,
    "max_calls_per_day": 2,
    # Overdue follow-up routing: owner first, then team leader, then admin
    "overdue_tl_minutes": 120,
    "overdue_admin_minutes": 480,
}

DEFAULT_TARGETS: dict = {
    "first_call_pct": 90,          # % of first calls within first_call_minutes
    "followup_on_time_pct": 95,    # % of follow-ups done by their due time
    "followup_grace_minutes": 15,  # done within due + grace counts as on time
    "low_sample_leads": 20,        # fewer leads than this = "low sample"
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


async def _get_json(db: AsyncSession, key: str):
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if not row or not row.value:
        return None
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return None


async def _set_json(db: AsyncSession, key: str, value, user_id: int | None = None) -> None:
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    text = json.dumps(value)
    if row:
        row.value = text
        row.updated_by = user_id
    else:
        db.add(Setting(key=key, value=text, updated_by=user_id))


async def get_automation(db: AsyncSession) -> dict:
    return _deep_merge(DEFAULT_AUTOMATION, await _get_json(db, AUTOMATION_KEY) or {})


async def save_automation(db: AsyncSession, value: dict, user_id: int | None) -> dict:
    merged = _deep_merge(DEFAULT_AUTOMATION, value or {})
    await _set_json(db, AUTOMATION_KEY, merged, user_id)
    return merged


async def get_targets(db: AsyncSession) -> dict:
    return _deep_merge(DEFAULT_TARGETS, await _get_json(db, TARGETS_KEY) or {})


async def save_targets(db: AsyncSession, value: dict, user_id: int | None) -> dict:
    merged = _deep_merge(DEFAULT_TARGETS, value or {})
    await _set_json(db, TARGETS_KEY, merged, user_id)
    return merged


async def get_aliases(db: AsyncSession) -> dict[str, int]:
    """Sheet "Person Calling" text (lower-case) -> user id."""
    data = await _get_json(db, ALIASES_KEY) or {}
    out: dict[str, int] = {}
    for k, v in data.items():
        try:
            out[" ".join(str(k).lower().split())] = int(v)
        except (TypeError, ValueError):
            continue
    return out


async def save_aliases(db: AsyncSession, value: dict[str, int], user_id: int | None) -> None:
    await _set_json(db, ALIASES_KEY, value, user_id)


async def get_go_live(db: AsyncSession) -> datetime | None:
    value = await _get_json(db, GO_LIVE_KEY)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


async def ensure_go_live(db: AsyncSession) -> tuple[datetime, bool]:
    """Returns (go_live_at, created_now). Leads first seen before go-live are
    historic: they never get SLA timers or automatic assignment."""
    existing = await get_go_live(db)
    if existing:
        return existing, False
    now = utcnow()
    await _set_json(db, GO_LIVE_KEY, now.isoformat())
    return now, True
