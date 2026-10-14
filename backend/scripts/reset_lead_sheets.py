#!/usr/bin/env python3
"""One-time reload of the telecalling leads from the team leaders' sheets.

The lead sheets are now one spreadsheet per team leader with one tab per
store (tele_call_sync.TL_SPREADSHEETS); the app used to read only each
spreadsheet's first tab under a city name ("Kerala", "Chennai", "Delhi").
This removes the leads imported that way, loads every store tab, and gives
each team leader their own tabs in Sheet Assignments.

Only leads that came from a sheet are removed (spreadsheet_id not empty);
leads created in the app, from the website or the Meta webhook stay. Their
activities, follow-ups, appointments, alerts and notifications go with them.

    python scripts/reset_lead_sheets.py           # dry run, changes nothing
    python scripts/reset_lead_sheets.py --apply   # reload
"""
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, func, select

from app.db.session import AsyncSessionLocal
from app.models.models import Role, TeleCallLead, TeleLeadActivity, TeleSheetAssignment, User
from app.services import tele_call_sync
from app.services.tele_call_sync import _fetch_sheet_rows, leads_sync_lock, refresh_sheet_list, sync_tele_call_leads

FROM_SHEET = func.coalesce(TeleCallLead.spreadsheet_id, "") != ""


async def main(apply: bool):
    sheets = await asyncio.to_thread(refresh_sheet_list)
    print(f"Lead tabs found: {len(sheets)}")
    total = 0
    for c in sheets:
        n = len(await asyncio.to_thread(_fetch_sheet_rows, c["spreadsheet_id"], c["tab"]))
        total += n
        print(f"  {c['team_leader']:9} {c['tab']:12} → '{c['tl_name']}': {n} leads")
    print(f"Leads in the sheets: {total}")

    async with AsyncSessionLocal() as db:
        now = dict((await db.execute(select(TeleCallLead.sheet_tl_name, func.count()).where(FROM_SHEET)
                                     .group_by(TeleCallLead.sheet_tl_name))).all())
        worked = (await db.execute(select(func.count(func.distinct(TeleLeadActivity.lead_id)))
                                   .where(TeleLeadActivity.user_id.isnot(None)))).scalar()
        owned = (await db.execute(select(func.count()).select_from(TeleCallLead).where(FROM_SHEET, TeleCallLead.owner_user_id.isnot(None)))).scalar()
        print(f"\nSheet leads in the database now: {sum(now.values())} {now}")
        print(f"  with an owner: {owned} | with activity logged by a person: {worked}")

        tls = {u.name.strip().upper(): u for u in (await db.execute(
            select(User).join(Role, Role.id == User.role_id).where(Role.name == "Team Leader"))).scalars().all()}
        wanted = Counter()
        for c in sheets:
            wanted[c["team_leader"]] += 1
        print("\nTeam leader → tabs to assign:")
        for name, n in wanted.items():
            u = tls.get(name)
            print(f"  {name}: {n} tabs" + ("" if u else "  ← NO USER WITH THIS NAME, skipped") + (" (account inactive)" if u and not u.is_active else ""))

        if not apply:
            print("\nDry run — nothing changed. Re-run with --apply to reload.")
            return
        # Hold the sync lock from the delete to the end of the load: a running
        # app's own one-minute sync would otherwise insert the same leads too.
        async with leads_sync_lock(db, wait_seconds=180) as got:
            if not got:
                print("\nAnother lead sync is still running. Nothing changed; try again in a minute.")
                return
            await db.execute(delete(TeleCallLead).where(FROM_SHEET))
            await db.execute(delete(TeleSheetAssignment).where(TeleSheetAssignment.sheet_tl_name.notin_([c["tl_name"] for c in sheets])))
            await db.commit()
            print(f"\nRemoved {sum(now.values())} old sheet leads.")
            result = await sync_tele_call_leads(db, locked=True)
        print("Loaded:", result["rows_synced"], "leads |", result["crm"])
        have = set((await db.execute(select(TeleSheetAssignment.user_id, TeleSheetAssignment.sheet_tl_name))).all())
        added = 0
        for c in tele_call_sync.TELE_CALL_SHEETS:
            u = tls.get(c["team_leader"])
            if u and (u.id, c["tl_name"]) not in have:
                db.add(TeleSheetAssignment(user_id=u.id, sheet_tl_name=c["tl_name"]))
                have.add((u.id, c["tl_name"]))
                added += 1
        await db.commit()
        print(f"Sheet assignments added: {added}")
        after = dict((await db.execute(select(TeleCallLead.sheet_tl_name, func.count()).where(FROM_SHEET)
                                       .group_by(TeleCallLead.sheet_tl_name))).all())
        print(f"Sheet leads in the database now: {sum(after.values())} {after}")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
