from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core.deps import get_db, require_permission
from ...models.models import Store, User, UserStoreAccess, Role
from ...services.store_merge_service import merge_store_into
from ...schemas import StoreCreate, StoreUpdate, StoreResponse

router = APIRouter(prefix="/stores", tags=["stores"])

# Sees every store, unconditionally, regardless of any UserStoreAccess row.
ALWAYS_SEE_ALL_ROLES = {"CEO", "SuperAdmin", "Admin", "COO"}


def _to_store_response(store: Store, tl: User | None) -> StoreResponse:
    return StoreResponse(
        id=store.id, name=store.name, team_leader_id=store.team_leader_id,
        team_leader_name=tl.name if tl else "",
        currency_code=store.currency_code,
        daily_target=float(store.daily_target),
        monthly_target=float(store.monthly_target),
        breakeven_revenue=float(store.breakeven_revenue),
        profitability_target=float(store.profitability_target),
        fixed_costs=float(store.fixed_costs),
        variable_cost_pct=float(store.variable_cost_pct),
        is_active=store.is_active, region=store.region or "",
        address=store.address or "", maps_link=store.maps_link or "",
        country=store.country or "India", needs_review=store.needs_review or False,
        created_at=store.created_at,
    )


@router.get("/", response_model=list[StoreResponse])
async def list_stores(
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("team_leaders", "view"),
):
    # A Team Leader's scope is their own branches (Store.team_leader_id).
    # CEO/SuperAdmin/Admin/COO always see every store, unconditionally.
    # Everyone else (Regional Manager included) sees only what's explicitly
    # granted via UserStoreAccess — nothing, if that's still empty. This
    # replaces the old "has the view permission and no UserStoreAccess rows
    # -> sees everything" fallback, which accidentally gave Regional Manager
    # (and anyone else who happened to have no grants yet) unrestricted
    # access instead of the "more than a TL, less than everything" scoping
    # they're actually meant to have.
    role_name = (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none()

    if role_name == "Team Leader":
        result = await db.execute(
            select(Store).where(Store.team_leader_id == user.id).order_by(Store.name)
        )
    elif role_name in ALWAYS_SEE_ALL_ROLES:
        result = await db.execute(select(Store).order_by(Store.name))
    else:
        store_ids = [sa.store_id for sa in user.store_access]
        if not store_ids:
            return []
        result = await db.execute(
            select(Store).where(Store.id.in_(store_ids)).order_by(Store.name)
        )

    stores = result.scalars().all()
    tl_cache = {}
    out = []
    for s in stores:
        if s.team_leader_id not in tl_cache:
            r = await db.execute(select(User).where(User.id == s.team_leader_id))
            tl_cache[s.team_leader_id] = r.scalar_one_or_none()
        tl = tl_cache.get(s.team_leader_id)
        out.append(_to_store_response(s, tl))
    return out


@router.post("/", response_model=StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(
    body: StoreCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("team_leaders", "create"),
):
    store = Store(
        name=body.name, team_leader_id=body.team_leader_id,
        currency_code=body.currency_code,
        daily_target=body.daily_target, monthly_target=body.monthly_target,
        breakeven_revenue=body.breakeven_revenue,
        profitability_target=body.profitability_target,
        fixed_costs=body.fixed_costs, variable_cost_pct=body.variable_cost_pct,
        is_active=body.is_active, region=body.region,
    )
    db.add(store)
    await db.commit()
    await db.refresh(store)
    r = await db.execute(select(User).where(User.id == store.team_leader_id))
    tl = r.scalar_one_or_none()
    return _to_store_response(store, tl)


@router.get("/{store_id}", response_model=StoreResponse)
async def get_store(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("team_leaders", "view"),
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if user.store_access:
        access_ids = [sa.store_id for sa in user.store_access]
        if store_id not in access_ids:
            raise HTTPException(status_code=403, detail="No access to this store")
    r = await db.execute(select(User).where(User.id == store.team_leader_id))
    tl = r.scalar_one_or_none()
    return _to_store_response(store, tl)


@router.put("/{store_id}", response_model=StoreResponse)
async def update_store(
    store_id: int,
    body: StoreUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("team_leaders", "edit"),
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(store, field, value)
    await db.commit()
    await db.refresh(store)
    r = await db.execute(select(User).where(User.id == store.team_leader_id))
    tl = r.scalar_one_or_none()
    return _to_store_response(store, tl)


@router.post("/{store_id}/merge-into/{target_store_id}")
async def merge_store(
    store_id: int,
    target_store_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("team_leaders", "edit"),
):
    """Merge a duplicate (usually needs_review) store into an existing one —
    moves every record that references it (sales, reviews, leads, staff,
    walk-ins, marketing metrics, user access/assignment, and its permanent
    MCP name memory) onto the target, correcting the target's country if
    the source's is more reliable, then deletes it. See
    store_merge_service.merge_store_into for the shared implementation used
    here and by every cleanup script."""
    if store_id == target_store_id:
        raise HTTPException(status_code=400, detail="Cannot merge a store into itself")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    result = await db.execute(select(Store).where(Store.id == target_store_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Target store not found")

    await merge_store_into(db, store, target)
    await db.commit()
    return {"message": f"Merged store {store_id} into {target_store_id}"}


@router.delete("/{store_id}")
async def delete_store(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("team_leaders", "delete"),
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    await db.delete(store)
    await db.commit()
    return {"message": "Store deleted"}
