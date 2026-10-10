"""Store daily form from the Dashboard Sheet ("BreakProtection — Master
Store Tracker"), tab "📋 DAILY SUBMISSION": one row per store per day.

    A DATE (28-Apr-26) | B STORE NAME | C LEADS (Outbound) | D INBOUND LEADS |
    E CALLS MADE | F CONTACTS MADE | G APPTS SET | H WALK-INS |
    I HOME DELIVERIES | J IN-STORE SALES | K REVENUE ₹ | L–R lost-sale reasons

The sheet pre-fills a row for every store and day, so a row counts only
once the store has typed a number in it. Its COO DASHBOARD / MONTHLY
SUMMARY tabs are formulas over this tab, so they are not imported.
Read-only towards the sheet.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import DailySubmission
from .google_sheets import _get_service, _read
from .walkins_sync import store_resolver

logger = logging.getLogger(__name__)

DASHBOARD_SHEET_ID = "1w893ChKglcqIxHnoDqJ6DfOEmQG51VGJqiEy5lg-yEA"
TAB = "📋 DAILY SUBMISSION"
COUNT_COLS = {2: "outbound_leads", 3: "inbound_leads", 4: "calls_made", 5: "calls_connected",
              6: "appointments_set", 7: "walk_ins", 8: "home_deliveries", 9: "walk_in_conversions"}
LEGACY_COUNTS = {"calls_made", "calls_connected", "walk_ins", "walk_in_conversions"}
REVENUE_COL = 10
LOST_COLS = {11: "Price too high", 12: "No show", 13: "Walk-in no buy", 14: "Product not available",
             15: "Will come later", 16: "Can't connect", 17: "Other"}
LAST_SYNC: dict = {}


def _num(text: str) -> Optional[float]:
    text = (text or "").replace("₹", "").replace(",", "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def parse_daily_submission(rows: list[list[str]]) -> list[dict]:
    """Filled rows of the tab as {"date", "store", <field>: value, ...}."""
    hdr = next((i for i, r in enumerate(rows) if r and r[0].strip().upper() == "DATE"), None)
    if hdr is None:
        return []
    out = []
    for r in rows[hdr + 1:]:
        if len(r) < 3 or not r[1].strip():
            continue
        try:
            day = datetime.strptime(r[0].strip(), "%d-%b-%y").date()
        except ValueError:
            continue
        cell = lambda i: _num(r[i]) if i < len(r) else None  # noqa: E731
        counts = {f: cell(i) for i, f in COUNT_COLS.items()}
        revenue = cell(REVENUE_COL)
        lost = {label: int(v) for i, label in LOST_COLS.items() if (v := cell(i))}
        if all(v is None for v in counts.values()) and revenue is None and not lost:
            continue  # pre-filled row the store hasn't filled in
        out.append({"date": day, "store": r[1].strip(), "revenue": revenue,
                    "lost_reasons": lost or None,
                    **{f: int(v) if v is not None else None for f, v in counts.items()}})
    return out


def fetch_daily_submission() -> list[dict]:
    return parse_daily_submission(_read(_get_service(), DASHBOARD_SHEET_ID, f"'{TAB}'!A1:R6000"))


async def sync_daily_submissions(db: AsyncSession, fetch=fetch_daily_submission) -> dict:
    rows = await asyncio.to_thread(fetch)
    resolve = await store_resolver(db)
    existing = {(s.store_id, s.date): s for s in (await db.execute(
        select(DailySubmission).where(DailySubmission.submitted_by.is_(None)))).scalars().all()}
    app_filled = set((await db.execute(select(DailySubmission.store_id, DailySubmission.date).where(
        DailySubmission.submitted_by.isnot(None)))).all())
    unmatched: set[str] = set()
    written = 0
    for r in rows:
        sid = resolve(r["store"])
        if not sid:
            unmatched.add(r["store"])
            continue
        if (sid, r["date"]) in app_filled:
            continue  # typed into the app's own form: that one stands
        sub = existing.get((sid, r["date"]))
        if sub is None:
            sub = existing[(sid, r["date"])] = DailySubmission(store_id=sid, date=r["date"])
            db.add(sub)
        sub.revenue = r["revenue"] or 0
        sub.lost_reasons = r["lost_reasons"]
        for f in COUNT_COLS.values():
            # the older columns are 0-not-blank; the new ones keep blank as blank
            setattr(sub, f, (r[f] or 0) if f in LEGACY_COUNTS else r[f])
        written += 1
    await db.commit()
    stats = {"at": datetime.utcnow().isoformat() + "Z", "rows": written, "unmatched_stores": sorted(unmatched)}
    LAST_SYNC.update(stats)
    if unmatched:
        logger.warning("DAILY SUBMISSION: no store for %s", sorted(unmatched))
    return stats
