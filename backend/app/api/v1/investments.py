from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core.deps import get_db, require_permission
from ...core.store_scope import allowed_store_ids, store_filter
from ...models.models import Investment, Store, User
from ...schemas import InvestmentCreate, InvestmentUpdate, InvestmentResponse

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("/", response_model=list[InvestmentResponse])
async def list_investments(
    store_id: int = None, category: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("investments", "view"),
):
    query = select(Investment)
    query = query.where(store_filter(Investment.store_id, await allowed_store_ids(user, db)))
    if store_id:
        query = query.where(Investment.store_id == store_id)
    if category:
        query = query.where(Investment.category == category)
    result = await db.execute(query.order_by(Investment.date.desc()))
    invs = result.scalars().all()
    store_cache = {}
    out = []
    for i in invs:
        if i.store_id and i.store_id not in store_cache:
            r = await db.execute(select(Store).where(Store.id == i.store_id))
            store_cache[i.store_id] = r.scalar_one_or_none()
        st = store_cache.get(i.store_id)
        out.append(InvestmentResponse(
            id=i.id, store_id=i.store_id, store_name=st.name if st else "Company-wide",
            category=i.category, description=i.description or "",
            amount=float(i.amount), date=i.date,
            created_by=i.created_by, created_at=i.created_at,
        ))
    return out


@router.post("/", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED)
async def create_investment(
    body: InvestmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("investments", "create"),
):
    inv = Investment(
        store_id=body.store_id, category=body.category,
        description=body.description, amount=body.amount,
        date=body.date, created_by=user.id,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    st_name = "Company-wide"
    if inv.store_id:
        r = await db.execute(select(Store).where(Store.id == inv.store_id))
        st = r.scalar_one_or_none()
        st_name = st.name if st else ""
    return InvestmentResponse(
        id=inv.id, store_id=inv.store_id, store_name=st_name,
        category=inv.category, description=inv.description or "",
        amount=float(inv.amount), date=inv.date,
        created_by=inv.created_by, created_at=inv.created_at,
    )


@router.get("/{inv_id}", response_model=InvestmentResponse)
async def get_investment(
    inv_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("investments", "view"),
):
    result = await db.execute(select(Investment).where(Investment.id == inv_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    st_name = "Company-wide"
    if inv.store_id:
        r = await db.execute(select(Store).where(Store.id == inv.store_id))
        st = r.scalar_one_or_none()
        st_name = st.name if st else ""
    return InvestmentResponse(
        id=inv.id, store_id=inv.store_id, store_name=st_name,
        category=inv.category, description=inv.description or "",
        amount=float(inv.amount), date=inv.date,
        created_by=inv.created_by, created_at=inv.created_at,
    )


@router.put("/{inv_id}", response_model=InvestmentResponse)
async def update_investment(
    inv_id: int, body: InvestmentUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("investments", "edit"),
):
    result = await db.execute(select(Investment).where(Investment.id == inv_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(inv, field, value)
    await db.commit()
    await db.refresh(inv)
    st_name = "Company-wide"
    if inv.store_id:
        r = await db.execute(select(Store).where(Store.id == inv.store_id))
        st = r.scalar_one_or_none()
        st_name = st.name if st else ""
    return InvestmentResponse(
        id=inv.id, store_id=inv.store_id, store_name=st_name,
        category=inv.category, description=inv.description or "",
        amount=float(inv.amount), date=inv.date,
        created_by=inv.created_by, created_at=inv.created_at,
    )


@router.delete("/{inv_id}")
async def delete_investment(
    inv_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("investments", "delete"),
):
    result = await db.execute(select(Investment).where(Investment.id == inv_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    await db.delete(inv)
    await db.commit()
    return {"message": "Investment deleted"}
