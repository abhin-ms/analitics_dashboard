#!/usr/bin/env python3
"""Give the stores MCP bills land on, but which sit under the "Unassigned"
placeholder, to the team leader whose lead sheet has that store's tab, so
their sales count on that team leader's dashboard and ranking.

Only a store still under "Unassigned" is moved; one already given a team
leader in the app is left as it is.

    python scripts/assign_store_team_leaders.py           # dry run
    python scripts/assign_store_team_leaders.py --apply
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, engine
from app.models.models import Role, Store, User

# store (as named in the app) -> team leader (whose lead sheet has its tab)
ASSIGN = {
    "Hyderabad Kukatpally": "ABDULLAH",   # tab Kukatpally
    "Mumbai Bandra": "ABDULLAH",          # tab Bandra
    "Tn Coimbatore": "SAM",               # tab Coimbatore
    "Kerala Trivandrum": "MICHAEL",       # tab TVM
    "Kerala Kasargod": "MICHAEL",         # tab Kasargod
    "Kerala Pathanamthitta": "MICHAEL",   # Michael's "PAT" store
    "Mangalore": "DEVIAHH",               # tab Mangalore
}
PLACEHOLDER = "unassigned"


async def main(apply: bool):
    async with AsyncSessionLocal() as db:
        changes = []
        for store_name, tl_name in ASSIGN.items():
            stores = (await db.execute(select(Store).where(func.lower(Store.name) == store_name.lower()))).scalars().all()
            tl = (await db.execute(select(User).join(Role, Role.id == User.role_id).where(
                Role.name == "Team Leader", func.lower(User.name) == tl_name.lower()))).scalars().first()
            if len(stores) != 1 or not tl:
                print(f"  skip {store_name}: {len(stores)} store(s) by that name, team leader {'found' if tl else 'NOT found'}")
                continue
            store = stores[0]
            current = await db.get(User, store.team_leader_id)
            if current and (current.name or "").strip().lower() != PLACEHOLDER:
                print(f"  keep {store_name}: already {current.name}")
                continue
            print(f"  {store_name}: {current.name if current else '-'} -> {tl.name}")
            changes.append((store, tl))
        if not apply:
            print(f"Dry run: {len(changes)} store(s) would move. Re-run with --apply.")
            return
        for store, tl in changes:
            store.team_leader_id = tl.id
        await db.commit()
        print(f"Moved {len(changes)} store(s).")


if __name__ == "__main__":
    async def run():
        try:
            await main("--apply" in sys.argv)
        finally:
            await engine.dispose()
    asyncio.run(run())
