#!/usr/bin/env python3
"""One-time rebuild of daily_submissions from the store daily-form sheets.

Two sheets fed this table:
  * the Operations sheet's "Master Log" — read with day and month swapped
    (12 July stored as 7 December, days above 12 dropped); it stopped on
    5 Sept;
  * the Dashboard Sheet's "DAILY SUBMISSION" tab — the stores' current form,
    never imported before (daily_submission_sync).

This deletes every row the sheet syncs wrote (submitted_by IS NULL; forms
typed in the app keep a submitter and are not touched), imports DAILY
SUBMISSION, then lets the Master Log fill only days DAILY SUBMISSION lacks.

    python scripts/fix_ops_submission_dates.py           # dry run, changes nothing
    python scripts/fix_ops_submission_dates.py --apply   # rebuild
"""
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select

from app.db.session import AsyncSessionLocal
from app.models.models import DailySubmission, SheetSource
from app.services.daily_submission_sync import fetch_daily_submission, sync_daily_submissions
from app.services.google_sheets import fetch_ops_data
from app.services.sheet_sync_service import SheetSyncService, parse_ops_date
from app.services.walkins_sync import store_resolver


def months(dates) -> dict:
    return dict(sorted(Counter(d.strftime("%Y-%m") for d in dates if d).items()))


async def main(apply: bool):
    form = await asyncio.to_thread(fetch_daily_submission)
    log = await asyncio.to_thread(fetch_ops_data)
    async with AsyncSessionLocal() as db:
        resolve = await store_resolver(db)
        print(f"DAILY SUBMISSION: {len(form)} filled rows {months(r['date'] for r in form)}")
        print(f"  stores not matched: {sorted({r['store'] for r in form if not resolve(r['store'])})}")
        print(f"Master Log: {len(log)} rows {months(parse_ops_date(r['date']) for r in log)}")
        synced = (await db.execute(select(DailySubmission).where(DailySubmission.submitted_by.is_(None)))).scalars().all()
        print(f"daily_submissions written by sheet syncs now: {len(synced)} {months(s.date for s in synced)}")
        if not apply:
            print("Dry run — nothing changed. Re-run with --apply to rebuild.")
            return
        await db.execute(delete(DailySubmission).where(DailySubmission.submitted_by.is_(None)))
        await db.commit()
        print(f"Deleted {len(synced)} rows.")
        print("Imported DAILY SUBMISSION:", await sync_daily_submissions(db))
        source = (await db.execute(select(SheetSource).where(SheetSource.label == "Operations Sheet"))).scalar_one()
        print("Master Log fill-in:", await SheetSyncService().sync_source(db, source.id))
        after = (await db.execute(select(DailySubmission.date))).scalars().all()
        print(f"daily_submissions now: {len(after)} {months(after)}")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
