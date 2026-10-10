"""Daily store walk-ins from the "Walk-ins Data" Google Sheet.

One tab per month ("Aug-26", "Sept-26", "Oct-26"), laid out as:

    row  "Date" | <TL> ...                    (team leader names)
    row         | Indiranagar |  |  |  | Thrissur | ...   (one store per 4 columns)
    row         | Actual Walkins | Dsr Walkins | Diff | (blank) | ...
    rows 01/10/2026 | 21 | 18 | ...           (DD/MM/YYYY, one per day)
    row  Total | ...

"Actual Walkins" is everyone who came in; "Dsr Walkins" the walk-ins the
store wrote in its daily sales report. Either may be blank. Read-only
towards the sheet.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Store, StoreMcpAlias, StoreWalkin
from .google_sheets import _get_service, _read
from .store_portfolio import shop_of

logger = logging.getLogger(__name__)

WALKINS_SHEET_ID = "1L5jMghIIFqJKqaohCZw1k6ARpDBJ2iDVBMCJwjMcmI8"
# Last run, for the integrations / freshness views.
LAST_SYNC: dict = {}


def _int(text: str) -> Optional[int]:
    text = (text or "").strip().replace(",", "")
    try:
        return int(float(text)) if text else None
    except ValueError:
        return None


def parse_walkins_tab(rows: list[list[str]]) -> list[tuple[str, date, Optional[int], Optional[int]]]:
    """(sheet store name, day, actual, dsr) for every filled cell pair of
    one month tab. Rows without a DD/MM/YYYY date (title, Total) are skipped."""
    hdr = next((i for i, r in enumerate(rows) if r and r[0].strip().lower() == "date"), None)
    if hdr is None or len(rows) < hdr + 3:
        return []
    names, subs = rows[hdr + 1], rows[hdr + 2]
    # each store's "Actual Walkins" column; "Dsr Walkins" is the next one
    stores = [(i, n.strip()) for i, n in enumerate(names)
              if n.strip() and i < len(subs) and subs[i].strip().lower().startswith("actual")]
    out = []
    for r in rows[hdr + 3:]:
        if not r:
            continue
        try:
            day = datetime.strptime(r[0].strip(), "%d/%m/%Y").date()
        except ValueError:
            continue
        for i, name in stores:
            actual = _int(r[i]) if i < len(r) else None
            dsr = _int(r[i + 1]) if i + 1 < len(r) else None
            if actual is not None or dsr is not None:
                out.append((name, day, actual, dsr))
    return out


def fetch_walkins() -> list[tuple[str, date, Optional[int], Optional[int]]]:
    service = _get_service()
    meta = service.spreadsheets().get(spreadsheetId=WALKINS_SHEET_ID).execute()
    out = []
    for sh in meta.get("sheets", []):
        title = sh["properties"]["title"]
        out.extend(parse_walkins_tab(_read(service, WALKINS_SHEET_ID, f"'{title}'!A1:CZ60")))
    return out


async def store_resolver(db: AsyncSession) -> Callable[[str], Optional[int]]:
    """Sheet store name → store id, by shop ("Hitec city" is the Hyderabad
    Hitech City shop). A shop with duplicate store records goes to the one
    MCP maintains, so it lines up with the sales figures."""
    stores = (await db.execute(select(Store.id, Store.name, Store.is_active).order_by(Store.id))).all()
    aliased = set((await db.execute(select(StoreMcpAlias.store_id))).scalars().all())
    by_shop: dict[str, int] = {}
    for sid, name, active in sorted(stores, key=lambda s: (s.id not in aliased, not s.is_active, s.id)):
        shop = shop_of(name)
        if shop and shop not in by_shop:
            by_shop[shop] = sid
    return lambda name: by_shop.get(shop_of(name) or "")


async def sync_walkins(db: AsyncSession, fetch=fetch_walkins) -> dict:
    rows = await asyncio.to_thread(fetch)
    resolve = await store_resolver(db)
    existing = {(w.store_id, w.date): w for w in (await db.execute(select(StoreWalkin))).scalars().all()}
    unmatched: set[str] = set()
    written = 0
    now = datetime.utcnow()
    for name, day, actual, dsr in rows:
        sid = resolve(name)
        if not sid:
            unmatched.add(name)
            continue
        w = existing.get((sid, day))
        if w is None:
            w = existing[(sid, day)] = StoreWalkin(store_id=sid, date=day)
            db.add(w)
        w.actual, w.dsr, w.sheet_store_name, w.synced_at = actual, dsr, name[:100], now
        written += 1
    await db.commit()
    stats = {"at": now.isoformat() + "Z", "rows": written, "unmatched_stores": sorted(unmatched)}
    LAST_SYNC.update(stats)
    if unmatched:
        logger.warning("Walk-ins sheet: no store for %s", sorted(unmatched))
    return stats
