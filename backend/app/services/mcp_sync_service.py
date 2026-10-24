import asyncio
import logging
import re
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError

from ..models.models import Store, User, McpBill, McpDailySale, Setting, StoreMcpAlias, CountrySalesSnapshot
from .common import get_or_create_unassigned_tl
from .mcp_branches import MCP_COUNTRIES
from .mcp_daily_sales import get_daily_sales, get_country_comparison, get_current_month_targets, get_transactions

logger = logging.getLogger(__name__)

LAST_SYNC_SETTING_KEY = "last_mcp_sync_at"

# Reduces (but, on its own, does NOT guarantee) races within THIS process
# between concurrent sync calls that both try to match/create the same shop.
# It does nothing across separate worker processes, which is why the actual
# guarantee against duplicates now comes from the unique constraint on
# stores.mcp_shop_name (migration 004) plus the atomic upsert below — a
# database-level guard that holds no matter how many processes race it at
# once. This lock just avoids unnecessary rollback churn in the common
# single-process case.
_store_match_lock = asyncio.Lock()


def _normalize_shop_name(name: str) -> str:
    """Collapse whitespace and normalize hyphen spacing so minor formatting
    differences from the MCP source (e.g. 'Solution -Guwahati' vs
    'Solution - Guwahati') don't get treated as distinct shops."""
    normalized = re.sub(r"\s*-\s*", " - ", name.strip())
    return re.sub(r"\s+", " ", normalized).strip()


def _extract_city_token(mcp_shop_name: str) -> str:
    """MCP shop names look like 'Heavenly Treasure - Velachery' — the token
    after the last ' - ' is usually the city/branch identifier that can be
    matched against an existing Sheets-sourced Store name. Assumes
    mcp_shop_name has already been run through _normalize_shop_name."""
    if " - " in mcp_shop_name:
        return mcp_shop_name.rsplit(" - ", 1)[-1].strip().lower()
    return mcp_shop_name.strip().lower()


async def _fix_country_if_wrong(store: Store, country_id: int, country_name: str) -> None:
    """Self-heals a store's country/mcp_country_id if a match was resolved
    for it under a different country than it's currently tagged with. This
    corrects pre-existing bad data (e.g. a UAE branch that was manually
    created with the Store model's default country="India" and never fixed)
    the moment MCP activity for it is next processed, instead of leaving
    that branch's revenue permanently misfiled under the wrong country in
    every country-scoped report."""
    if store.country != country_name or store.mcp_country_id != country_id:
        store.country = country_name
        store.mcp_country_id = country_id


async def _record_alias(db: AsyncSession, store_id: int, mcp_shop_name: str) -> None:
    """Permanently remembers that this MCP name belongs to this store, so a
    future merge/delete of the Store row that currently holds it can never
    erase the fact that this name was already resolved once."""
    stmt = mysql_insert(StoreMcpAlias).values(store_id=store_id, mcp_shop_name=mcp_shop_name)
    stmt = stmt.on_duplicate_key_update(store_id=stmt.inserted.store_id)
    await db.execute(stmt)


async def _match_or_create_store(
    db: AsyncSession, mcp_shop_name: str, country_id: int, country_name: str
) -> tuple[Store, bool]:
    """Resolve an MCP shop name to a Store row. Returns (store, created)."""
    mcp_shop_name = _normalize_shop_name(mcp_shop_name)

    async with _store_match_lock:
        # Check every name ever confirmed for a store — not just whatever is
        # CURRENTLY in Store.mcp_shop_name — so a name that was already
        # resolved once (even if the branch that first claimed it has since
        # been merged into a different one) is recognized instantly instead
        # of spinning up a fresh "needs review" duplicate every time it
        # resurfaces.
        alias = (await db.execute(
            select(StoreMcpAlias).where(StoreMcpAlias.mcp_shop_name == mcp_shop_name)
        )).scalar_one_or_none()
        if alias:
            aliased_store = (await db.execute(
                select(Store).where(Store.id == alias.store_id)
            )).scalar_one_or_none()
            if aliased_store:
                await _fix_country_if_wrong(aliased_store, country_id, country_name)
                return aliased_store, False

        result = await db.execute(
            select(Store).where(Store.mcp_shop_name == mcp_shop_name).order_by(Store.id)
        )
        matches = result.scalars().all()
        if matches:
            if len(matches) > 1:
                logger.warning(
                    "Duplicate stores share mcp_shop_name=%r (ids=%s) — using the oldest, "
                    "ignoring the rest. Run scripts/dedupe_mcp_stores.py to clean this up.",
                    mcp_shop_name, [s.id for s in matches],
                )
            await _record_alias(db, matches[0].id, mcp_shop_name)
            await _fix_country_if_wrong(matches[0], country_id, country_name)
            return matches[0], False

        if country_id == 1:
            # Try to match an existing India store (created by the Sheets sync)
            # by its city/branch token, since MCP and Sheets use different
            # naming conventions for the same physical branch.
            token = _extract_city_token(mcp_shop_name)
            candidates = (await db.execute(
                select(Store).where(Store.country == "India", Store.mcp_shop_name.is_(None))
            )).scalars().all()
            matches = [s for s in candidates if token and token in s.name.lower()]
            if len(matches) == 1:
                try:
                    # A SAVEPOINT (not a full rollback) so that if this
                    # specific update conflicts, we only discard THIS
                    # change — not the rest of the batch this call is
                    # partway through processing.
                    async with db.begin_nested():
                        matches[0].mcp_shop_name = mcp_shop_name
                        matches[0].mcp_country_id = country_id
                        await db.flush()
                        await _record_alias(db, matches[0].id, mcp_shop_name)
                    return matches[0], False
                except IntegrityError:
                    # Another process claimed this exact mcp_shop_name in the
                    # gap between our SELECT and this flush (the unique
                    # constraint from migration 004 caught it) — use
                    # whichever row actually won instead.
                    winner = (await db.execute(
                        select(Store).where(Store.mcp_shop_name == mcp_shop_name)
                    )).scalar_one()
                    return winner, False
            # 0 or >1 matches: ambiguous, fall through to create a new store
            # flagged for manual review rather than guessing.

        # Atomic insert-or-get against the unique constraint on
        # mcp_shop_name, instead of a plain INSERT after the SELECT above.
        # If another process (a different worker, not just a different
        # asyncio task in this one) inserted the same shop a moment ago,
        # this converts into a no-op UPDATE and returns THAT row's id —
        # guaranteeing exactly one Store row per mcp_shop_name no matter how
        # many processes race to create it at the same instant.
        placeholder_tl = await get_or_create_unassigned_tl(db)
        stmt = mysql_insert(Store).values(
            name=mcp_shop_name,
            team_leader_id=placeholder_tl.id,
            country=country_name,
            mcp_country_id=country_id,
            mcp_shop_name=mcp_shop_name,
            needs_review=True,
            is_active=True,
        )
        stmt = stmt.on_duplicate_key_update(updated_at=stmt.inserted.updated_at)
        result = await db.execute(stmt)
        await db.flush()
        # MySQL reports affected-rows as 1 for a fresh insert and 2 when the
        # ON DUPLICATE KEY UPDATE branch fired instead — that's how we tell
        # whether we actually created it or just found the winner.
        created = result.rowcount == 1
        store = (await db.execute(select(Store).where(Store.id == result.lastrowid))).scalar_one()
        if not created:
            logger.info(
                "Concurrent sync already created the store for mcp_shop_name=%r (id=%s) — reusing it.",
                mcp_shop_name, store.id,
            )
        await _record_alias(db, store.id, mcp_shop_name)
        return store, created


async def _set_last_sync_time(db: AsyncSession) -> None:
    result = await db.execute(select(Setting).where(Setting.key == LAST_SYNC_SETTING_KEY))
    setting = result.scalar_one_or_none()
    now_str = datetime.utcnow().isoformat()
    if setting:
        setting.value = now_str
    else:
        db.add(Setting(key=LAST_SYNC_SETTING_KEY, value=now_str))


def _report_row(r: dict) -> dict:
    """A Sales Report API row in the shape store_bills takes."""
    mobile = (r.get("mobile_number") or "").strip()
    digits = re.sub(r"\D", "", mobile)
    return {
        "id": r.get("purchase_id"), "date": (r.get("created_date") or "")[:10], "shop": r.get("shop_name"),
        "category": r.get("purchase_category"), "model": r.get("model"), "imei": r.get("imei_number"),
        "amount": r.get("sale_amount") if r.get("sale_amount") is not None else r.get("amount"),
        "discount": r.get("discount"), "paid": (r.get("payment_status") or "").lower() == "paid",
        "customer_name": (r.get("customer_name") or "").strip()[:150] or None,
        "mobile": mobile[:30] or None, "mobile10": digits[-10:] if len(digits) >= 10 else None,
        "salesman": (r.get("salesman") or "").strip()[:150] or None, "purchase_type": (r.get("purchase_type") or "")[:80] or None,
        "is_care_plus": r.get("is_care_plus_covered"), "installation_status": (r.get("installation_status") or "")[:20] or None,
        "payment_status": (r.get("payment_status") or "")[:20] or None, "mcp_shop_id": r.get("shop_id"),
    }


EXTRA_BILL_FIELDS = ("customer_name", "mobile", "mobile10", "salesman", "purchase_type", "is_care_plus",
                     "installation_status", "payment_status", "mcp_shop_id")


async def store_bills(db: AsyncSession, country_id: int, transactions: list[dict]) -> int:
    """Upsert one McpBill per bill; returns how many were new. Rows come from
    the Sales Report API (_report_row) or, as a fallback, the MCP's
    transaction list, which has no customer / salesman fields."""
    ids = [t["id"] for t in transactions if t.get("id")]
    if not ids:
        return 0
    existing = {}
    for i in range(0, len(ids), 1000):
        existing.update({b.id: b for b in (await db.execute(select(McpBill).where(McpBill.id.in_(ids[i:i + 1000])))).scalars().all()})
    new = 0
    now = datetime.utcnow()
    for t in transactions:
        if not t.get("id"):
            continue
        try:
            day = date.fromisoformat(t["date"])
        except (TypeError, ValueError):
            continue
        bill = existing.get(t["id"])
        if bill is None:
            bill = existing[t["id"]] = McpBill(id=t["id"])
            db.add(bill)
            new += 1
        # same spelling as the store aliases ("X -CLT" → "X - CLT"), so a bill finds its store
        bill.date, bill.shop, bill.category = day, _normalize_shop_name(t.get("shop") or "")[:150], (t.get("category") or "")[:60]
        bill.model, bill.imei = (t.get("model") or "")[:150], (t.get("imei") or "")[:40]
        bill.amount, bill.discount, bill.paid = t.get("amount") or 0, t.get("discount") or 0, bool(t.get("paid"))
        bill.country_id, bill.synced_at = country_id, now
        if "mobile10" in t:  # a Sales Report row: the fuller record
            for f in EXTRA_BILL_FIELDS:
                setattr(bill, f, t.get(f))
    await db.flush()
    return new


async def fetch_bills(country_id: int, from_date: str, to_date: str) -> list[dict]:
    """The range's bills: the Sales Report API's full records, or the MCP's
    shorter transaction list if that API can't be reached."""
    from .smart_service_client import smart_service
    try:
        return [_report_row(r) for r in await smart_service.sales_report(from_date, to_date, country_id)]
    except Exception as e:
        logger.warning("Sales Report API failed for country %s (%s); using the MCP transaction list", country_id, e)
        return await get_transactions(country_id, from_date, to_date)


async def sync_mcp_sales(
    db: AsyncSession, from_date: str = None, to_date: str = None
) -> dict:
    """Pull sales from MCP for every country (India included) over the given
    date range (defaults to month-to-date) and persist into mcp_daily_sales.
    """
    today = date.today()
    if not to_date:
        to_date = today.strftime("%Y-%m-%d")
    if not from_date:
        from_date = today.replace(day=1).strftime("%Y-%m-%d")

    rows_synced = 0
    new_stores = 0
    review_needed = 0
    errors: list[str] = []

    for country in MCP_COUNTRIES:
        try:
            daily_rows = await get_daily_sales(country["id"], from_date, to_date)
        except Exception as e:
            logger.warning("MCP sync failed for %s: %s", country["name"], e)
            errors.append(f"{country['name']}: {e}")
            continue

        # Keep the bills themselves too (same fetch, cached): a bill number
        # noted on a lead is checked against these — see crm/bill_verify.py.
        # In a savepoint: a concurrent sync can insert the same bill first
        # (duplicate key on flush), and without one that failed flush would
        # leave the whole session unusable and fail the sales sync below too.
        try:
            bills = await fetch_bills(country["id"], from_date, to_date)
            async with db.begin_nested():
                await store_bills(db, country["id"], bills)
        except Exception as e:
            logger.warning("Storing MCP bills failed for %s: %s", country["name"], e)

        # Keep each already-known store's Store.monthly_target current from
        # MCP's live target sheet, independent of whether that store has
        # any recent transactions. Deriving "target" from transaction
        # history alone has two failure modes: a store with zero activity
        # this month keeps reporting a stale target from whenever it last
        # happened to sync, and a store with activity but no target row
        # for the exact date being read shows 0 even though MCP has a real
        # target for it. Reading the current-month sheet directly and
        # writing it onto the Store record sidesteps both.
        #
        # Every store with a known MCP alias is explicitly WRITTEN here —
        # not just the ones this month's sheet happens to mention. A shop
        # whose target was discontinued (or the store simply hasn't synced
        # in a while, like a branch with no activity since July) needs to
        # be reset to 0, not left holding whatever value it had the last
        # time it happened to appear — an earlier version of this only
        # updated stores present in the current fetch and silently left
        # stale non-zero targets on everything else, which is exactly the
        # kind of staleness this whole fix exists to prevent.
        try:
            raw_current_targets = await get_current_month_targets(country["id"])
            # Keys come straight from MCP's raw shop names, but aliases are
            # stored normalized (see _normalize_shop_name) — normalize here
            # too, or a shop reported with different spacing than what was
            # recorded as its alias would never match.
            current_targets = {_normalize_shop_name(k): v for k, v in raw_current_targets.items()}
            stores_with_alias = (await db.execute(
                select(Store).join(StoreMcpAlias, StoreMcpAlias.store_id == Store.id)
                .where(Store.country == country["name"])
                .distinct()
            )).scalars().all()
            for store in stores_with_alias:
                store_aliases = (await db.execute(
                    select(StoreMcpAlias.mcp_shop_name).where(StoreMcpAlias.store_id == store.id)
                )).scalars().all()
                # A store can carry more than one known name: a renamed
                # shop, or several branches kept as one store ("Speedy" =
                # five Speedy branches, each with its own target). Its sales
                # add up over all of them, so its target does too. A month's
                # report lists each shop once, so a renamed shop isn't
                # counted twice; 0 if none of its names appear this month.
                store.monthly_target = sum(
                    current_targets.get(_normalize_shop_name(name), 0.0) for name in set(store_aliases)
                )
        except Exception as e:
            logger.warning("Current-month target refresh failed for %s: %s", country["name"], e)

        # Resolve every row to its target store FIRST, then group by
        # (store_id, date) before writing anything. This matters once a
        # store has more than one known MCP name (aliases recorded via
        # merges) — MCP can report two of those names as separate rows on
        # the same date, and if each were upserted individually with
        # overwrite semantics, the second write would silently replace the
        # first instead of adding to it, permanently losing that revenue.
        # Summing in Python first, then writing one row per (store, date),
        # keeps the "overwrite is safe to re-run" property that ordinary
        # (non-aliased) stores rely on for idempotent re-syncs, while still
        # combining aliased names correctly.
        grouped: dict[tuple[int, str], dict] = {}
        for row in daily_rows:
            if not row.get("store"):
                continue
            store, created = await _match_or_create_store(
                db, row["store"], country["id"], country["name"]
            )
            if created:
                new_stores += 1
                if store.needs_review:
                    review_needed += 1

            key = (store.id, row["date"])
            g = grouped.setdefault(key, {
                "store_id": store.id, "date": row["date"],
                "revenue": 0.0, "units_sold": 0, "new_sale_count": 0,
                "replacement_count": 0, "return_count": 0, "target": 0.0,
            })
            g["revenue"] += row.get("revenue", 0)
            g["units_sold"] += row.get("units_sold", 0)
            g["new_sale_count"] += row.get("new_sale_count", 0)
            g["replacement_count"] += row.get("replacement_count", 0)
            g["return_count"] += row.get("return_count", 0)
            # Target is a per-shop monthly figure, not something to sum
            # across aliases of the same physical branch — take whichever
            # is largest so a placeholder/zero target on one alias doesn't
            # clobber a real one already seen for this store+date.
            g["target"] = max(g["target"], row.get("target", 0))

        for g in grouped.values():
            sub_date = datetime.strptime(g["date"], "%Y-%m-%d").date()
            # Atomic upsert (not select-then-insert) so concurrent syncs for
            # an overlapping date range — e.g. two report requests triggering
            # a lazy backfill at the same time — can't race on the unique
            # (store_id, date) constraint.
            stmt = mysql_insert(McpDailySale).values(
                store_id=g["store_id"], date=sub_date,
                revenue=g["revenue"], units_sold=g["units_sold"],
                new_sale_count=g["new_sale_count"],
                replacement_count=g["replacement_count"],
                return_count=g["return_count"],
                target=g["target"], currency="",
                synced_at=datetime.utcnow(),
            )
            stmt = stmt.on_duplicate_key_update(
                revenue=stmt.inserted.revenue,
                units_sold=stmt.inserted.units_sold,
                new_sale_count=stmt.inserted.new_sale_count,
                replacement_count=stmt.inserted.replacement_count,
                return_count=stmt.inserted.return_count,
                target=stmt.inserted.target,
                synced_at=stmt.inserted.synced_at,
            )
            await db.execute(stmt)
            rows_synced += 1

    # Snapshot MCP's own country-comparison totals (it does its own USD
    # conversion using current rates) so the International Sales chart can
    # read a stored value instead of calling MCP on every dashboard load —
    # same principle as everything else above, just for this one view.
    #
    # Every country in MCP_COUNTRIES is written every run, not just the
    # ones MCP's comparison happens to mention this time — a country that
    # genuinely has no sales this month is written as an explicit zero.
    # Only upserting rows for countries present in `comparison` (the old
    # behavior) meant a country that drops out of MCP's comparison (e.g.
    # Malaysia, Bahrain, UK having no sales this month) kept showing
    # whatever number was last recorded, possibly weeks old, forever —
    # since nothing ever cleared it.
    _CURRENCY_BY_COUNTRY = {
        "INDIA": "INR", "OMAN": "OMR", "PAKISTAN": "PKR", "UAE": "AED",
        "MALAYSIA": "MYR", "UK": "GBP", "BAHRAIN": "BHD", "QATAR": "QAR",
    }
    try:
        comparison = await get_country_comparison(from_date, to_date)
        comparison_by_country = {c["country"].upper(): c for c in comparison}
        for mcp_country in MCP_COUNTRIES:
            key = mcp_country["name"].upper()
            c = comparison_by_country.get(key)
            if c:
                local_amount, local_currency, usd_amount = c["local_amount"], c["local_currency"], c["usd_amount"]
            else:
                local_amount, local_currency, usd_amount = 0.0, _CURRENCY_BY_COUNTRY.get(key, ""), 0.0
            stmt = mysql_insert(CountrySalesSnapshot).values(
                country=key, local_amount=local_amount,
                local_currency=local_currency, usd_amount=usd_amount,
                synced_at=datetime.utcnow(),
            )
            stmt = stmt.on_duplicate_key_update(
                local_amount=stmt.inserted.local_amount,
                local_currency=stmt.inserted.local_currency,
                usd_amount=stmt.inserted.usd_amount,
                synced_at=stmt.inserted.synced_at,
            )
            await db.execute(stmt)
    except Exception as e:
        logger.warning("Country comparison snapshot failed: %s", e)
        errors.append(f"country-comparison: {e}")

    await _set_last_sync_time(db)
    await db.commit()

    return {
        "status": "ok" if not errors else "partial",
        "rows_synced": rows_synced,
        "new_stores": new_stores,
        "stores_needing_review": review_needed,
        "countries_synced": len(MCP_COUNTRIES) - len(errors),
        "errors": errors,
    }
