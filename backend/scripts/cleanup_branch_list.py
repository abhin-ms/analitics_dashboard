#!/usr/bin/env python3
"""Cleans up legacy Google-Sheets-created stores that show up under India
on the dashboard's branch list — international placeholders (Online, Bahrain,
UK, Oman "IK" shops...) and legacy duplicates of real branches ("Kerala
Kasargod" next to "Kasaragod", "Bangalore - Indira Nagar" next to "Bangalore
Indiranagar").

For every active, confirmed India-tagged store with NO MCP alias:
  - close name match to another store  -> MERGE into it (its data moves over
    and its name is recorded as a permanent alias, so the Sheets sync can
    never re-create it)
  - otherwise                          -> DEACTIVATE (is_active=False). Not
    deleted: the row stays so the Sheets sync finds it by name instead of
    creating a fresh active copy, and nothing is lost.

Stores that DO have MCP aliases are never touched — likely duplicate pairs
among them are only printed for you to decide on.

Prints the full plan and asks for one 'yes' before changing anything.
"""
import asyncio
import re
import sys
import os
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models.models import Store, StoreMcpAlias, McpDailySale
from app.services.store_merge_service import merge_store_into

_PREFIXES = {"kerala", "tn", "chennai", "bangalore", "hyderabad", "mumbai", "delhi", "store"}
# Short codes used as branch names in the old Sheets data.
_ABBREVIATIONS = {"tvm": "trivandrum", "pat": "pathanamthitta", "clt": "calicut"}
SIMILARITY = 0.85


def _key(name: str) -> str:
    words = [w for w in re.findall(r"[a-z]+", name.lower())]
    core = [w for w in words if w not in _PREFIXES] or words
    joined = "".join(core)
    return _ABBREVIATIONS.get(joined, joined)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _key(a), _key(b)).ratio()


async def main():
    async with AsyncSessionLocal() as db:
        aliased_ids = {r[0] for r in (await db.execute(select(StoreMcpAlias.store_id).distinct())).all()}
        stores = (await db.execute(
            select(Store).where(Store.country == "India", Store.is_active == True, Store.needs_review == False)
        )).scalars().all()
        aliased = [s for s in stores if s.id in aliased_ids]
        legacy = [s for s in stores if s.id not in aliased_ids]

        merges, deactivations, skipped = [], [], []
        for s in legacy:
            rev = float((await db.execute(
                select(func.coalesce(func.sum(McpDailySale.revenue), 0)).where(McpDailySale.store_id == s.id)
            )).scalar() or 0)
            if rev > 0:
                skipped.append((s, rev))
                continue
            best, best_score = None, 0.0
            for other in stores:
                if other.id == s.id:
                    continue
                score = _similar(s.name, other.name)
                # prefer an MCP-managed twin on ties
                if score > best_score or (score == best_score and best is not None and other.id in aliased_ids and best.id not in aliased_ids):
                    best, best_score = other, score
            if best and best_score >= SIMILARITY and best.id in aliased_ids:
                merges.append((s, best, best_score))
            else:
                deactivations.append(s)

        print(f"{len(merges)} legacy store(s) to MERGE into an MCP-managed twin:")
        for s, t, score in merges:
            print(f"  MERGE  {s.name!r:40} -> {t.name!r}   (match {score:.0%})")
        print(f"\n{len(deactivations)} legacy store(s) to DEACTIVATE (no MCP twin — placeholders / international leftovers):")
        for s in deactivations:
            print(f"  OFF    {s.name!r}")
        if skipped:
            print(f"\n{len(skipped)} legacy store(s) SKIPPED because they hold MCP revenue — review by hand:")
            for s, rev in skipped:
                print(f"  ?      {s.name!r}  revenue={rev:,.2f}")

        print("\nLikely duplicate pairs among MCP-managed stores (NOT touched — decide yourself):")
        seen = set()
        any_pair = False
        for i, a in enumerate(aliased):
            for b in aliased[i + 1:]:
                score = _similar(a.name, b.name)
                if score >= SIMILARITY and (a.id, b.id) not in seen:
                    seen.add((a.id, b.id))
                    any_pair = True
                    print(f"  {a.name!r} (id={a.id})  <->  {b.name!r} (id={b.id})   match {score:.0%}")
        if not any_pair:
            print("  none found")

        if not merges and not deactivations:
            print("\nNothing to apply.")
            return
        answer = input(f"\nApply {len(merges)} merge(s) and {len(deactivations)} deactivation(s)? Type 'yes' to proceed: ").strip().lower()
        if answer != "yes":
            print("Aborted — nothing changed.")
            return

        for s, t, _ in merges:
            await merge_store_into(db, s, t)
        for s in deactivations:
            s.is_active = False
        await db.commit()
        print(f"\nDone. Merged {len(merges)}, deactivated {len(deactivations)}.")


if __name__ == "__main__":
    asyncio.run(main())
