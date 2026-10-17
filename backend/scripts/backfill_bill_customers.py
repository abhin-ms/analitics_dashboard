#!/usr/bin/env python3
"""One-time refresh of saved MCP bills, so bills saved before the vendor
started filling customer name and mobile get them too, then match sales to
leads by mobile.

The 15-minute MCP sync only re-reads the current month, so older bills
keep their empty customer fields until refreshed once with this.

    python scripts/backfill_bill_customers.py              # dry run: counts only
    python scripts/backfill_bill_customers.py --apply      # refresh + match
    python scripts/backfill_bill_customers.py --days 60 --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, engine
from app.models.models import McpBill
from app.services.crm.bill_verify import MATCH_LOOKBACK_DAYS, run_bill_matching
from app.services.mcp_sync_service import MCP_COUNTRIES, fetch_bills, store_bills


async def main(days: int, apply: bool):
    start, end = date.today() - timedelta(days=days), date.today()
    async with AsyncSessionLocal() as db:
        saved = (await db.execute(select(func.count(McpBill.id), func.count(McpBill.mobile10)).where(
            McpBill.date >= start))).one()
        print(f"Saved bills since {start}: {saved[0]}, with a customer mobile: {saved[1]}")
        fetched = {}
        for country in MCP_COUNTRIES:
            rows = await fetch_bills(country["id"], start.isoformat(), end.isoformat())
            fetched[country["id"]] = rows
            print(f"  {country['name']}: {len(rows)} bills from MCP, {sum(1 for r in rows if r.get('mobile10'))} with a mobile")
        if not apply:
            print("Dry run — nothing changed. Re-run with --apply to refresh the bills and match them to leads.")
            return
        for country_id, rows in fetched.items():
            await store_bills(db, country_id, rows)
        await db.commit()
        after = (await db.execute(select(func.count(McpBill.mobile10)).where(McpBill.date >= start))).scalar()
        print(f"Refreshed. Saved bills with a customer mobile now: {after}")
        print("Matching sales to leads:", await run_bill_matching(db))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=MATCH_LOOKBACK_DAYS)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()

    async def run():
        try:
            await main(a.days, a.apply)
        finally:
            await engine.dispose()  # close DB connections before the loop ends
    asyncio.run(run())
