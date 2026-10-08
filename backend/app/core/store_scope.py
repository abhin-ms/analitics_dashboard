"""Which stores a user's store-level figures cover — one fail-closed rule for
every legacy route (dashboard, leads, tasks, submissions, reports, ...).

  * CEO, SuperAdmin, Admin, COO: every store (None)
  * otherwise (Regional Manager included — "more than a TL, less than
    everything") the union of: explicit store_access rows, the user's own
    store_id, and the stores a Team Leader runs
  * nothing matched: an empty list, which must mean "no rows", never "all"

Use `store_filter` to turn the result into a WHERE clause so an empty list
can't be mistaken for "no filter" by an `if store_ids:` check.
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Role, Store, User

# Sees every store, unconditionally, regardless of any UserStoreAccess row.
ALWAYS_SEE_ALL_ROLES = {"CEO", "SuperAdmin", "Admin", "COO"}


async def allowed_store_ids(user: User, db: AsyncSession) -> Optional[list[int]]:
    """None = every store; otherwise exactly these (possibly none)."""
    role = (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none()
    if role in ALWAYS_SEE_ALL_ROLES:
        return None
    ids = {sa.store_id for sa in user.store_access}
    if user.store_id:
        ids.add(user.store_id)
    if role == "Team Leader":
        ids.update((await db.execute(select(Store.id).where(Store.team_leader_id == user.id))).scalars().all())
    return sorted(ids)


def store_filter(column, store_ids: Optional[list[int]]):
    """WHERE clause limiting `column` to the allowed stores."""
    return true() if store_ids is None else column.in_(store_ids)


def check_store(store_ids: Optional[list[int]], store_id: Optional[int]) -> None:
    """403 unless `store_id` is inside the allowed stores."""
    if store_ids is not None and store_id not in store_ids:
        raise HTTPException(status_code=403, detail="No access to this store")
