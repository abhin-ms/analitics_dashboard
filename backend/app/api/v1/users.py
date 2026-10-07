from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from ...core.deps import get_db, require_permission
from ...core.security import hash_password
from ...models.models import (
    User, Role, UserStoreAccess, Store, DailySubmission, Lead, LeadActivity,
    Task, Investment, SheetSource, Setting, AISummaryConfig, AuditLog,
    TeleSheetAssignment,
)
from ...schemas import UserCreate, UserUpdate, UserResponse, ResetPasswordRequest
from ...services.common import get_or_create_unassigned_tl

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("users", "view"),
):
    result = await db.execute(select(User).order_by(User.name).options(selectinload(User.store_access)))
    users = result.scalars().all()
    role_cache = {}
    out = []
    for u in users:
        if u.role_id not in role_cache:
            r = await db.execute(select(Role).where(Role.id == u.role_id))
            role_cache[u.role_id] = r.scalar_one_or_none()
        rl = role_cache.get(u.role_id)
        store_ids = [sa.store_id for sa in u.store_access]
        out.append(UserResponse(
            id=u.id, name=u.name, email=u.email, role_id=u.role_id,
            role_name=rl.name if rl else "", is_active=u.is_active,
            store_ids=store_ids, store_id=u.store_id, team_leader_id=u.team_leader_id,
            created_at=u.created_at,
        ))
    return out


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("users", "create"),
):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    role = await db.execute(select(Role).where(Role.id == body.role_id))
    role = role.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role_id")

    user = User(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        role_id=body.role_id,
        is_active=body.is_active,
        store_id=body.store_id,
        team_leader_id=body.team_leader_id,
    )
    db.add(user)
    await db.flush()

    for sid in body.store_ids:
        db.add(UserStoreAccess(user_id=user.id, store_id=sid))
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=role.name, is_active=user.is_active,
        store_ids=body.store_ids, store_id=user.store_id, team_leader_id=user.team_leader_id,
        created_at=user.created_at,
    )


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("users", "edit"),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1  # sign out every device
    await db.commit()
    return {"message": f"Password updated for {user.name}"}


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("users", "view"),
):
    result = await db.execute(select(User).where(User.id == user_id).options(selectinload(User.store_access)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    r = await db.execute(select(Role).where(Role.id == user.role_id))
    rl = r.scalar_one_or_none()
    store_ids = [sa.store_id for sa in user.store_access]
    return UserResponse(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=rl.name if rl else "", is_active=user.is_active,
        store_ids=store_ids, store_id=user.store_id, team_leader_id=user.team_leader_id,
        created_at=user.created_at,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("users", "edit"),
):
    result = await db.execute(select(User).where(User.id == user_id).options(selectinload(User.store_access)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.role_id is not None:
        role_exists = await db.execute(select(Role).where(Role.id == body.role_id))
        if not role_exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Invalid role_id")

    was_active = user.is_active
    for field, value in body.model_dump(exclude_unset=True, exclude={"store_ids", "password"}).items():
        setattr(user, field, value)

    # A new password or deactivation signs the user out on every device.
    if body.password:
        user.password_hash = hash_password(body.password)
    if body.password or (was_active and not user.is_active):
        user.token_version = (user.token_version or 0) + 1

    if body.store_ids is not None:
        await db.execute(
            UserStoreAccess.__table__.delete().where(UserStoreAccess.user_id == user_id)
        )
        for sid in body.store_ids:
            db.add(UserStoreAccess(user_id=user_id, store_id=sid))

    await db.commit()
    await db.refresh(user)
    r = await db.execute(select(Role).where(Role.id == user.role_id))
    rl = r.scalar_one_or_none()
    store_ids = [sa.store_id for sa in user.store_access]
    return UserResponse(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=rl.name if rl else "", is_active=user.is_active,
        store_ids=store_ids, store_id=user.store_id, team_leader_id=user.team_leader_id,
        created_at=user.created_at,
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("users", "delete"),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email == "unassigned@system.local":
        raise HTTPException(status_code=400, detail="Cannot delete the system 'Unassigned' placeholder account")

    try:
        owned_stores = await db.execute(select(Store).where(Store.team_leader_id == user_id))
        owned_stores = owned_stores.scalars().all()
        if owned_stores:
            placeholder = await get_or_create_unassigned_tl(db)
            for store in owned_stores:
                store.team_leader_id = placeholder.id

        # Nullable FKs pointing at this user — detach the "who" reference,
        # keep the row (no data loss).
        for model, col in (
            (DailySubmission, DailySubmission.submitted_by),
            (Lead, Lead.assigned_to),
            (LeadActivity, LeadActivity.created_by),
            (Task, Task.assigned_to),
            (Investment, Investment.created_by),
            (SheetSource, SheetSource.created_by),
            (Setting, Setting.updated_by),
            (AISummaryConfig, AISummaryConfig.updated_by),
            (AuditLog, AuditLog.user_id),
            (User, User.team_leader_id),
        ):
            await db.execute(update(model).where(col == user_id).values(**{col.key: None}))

        # NOT NULL FK, meaningless without the user.
        await db.execute(
            TeleSheetAssignment.__table__.delete().where(TeleSheetAssignment.user_id == user_id)
        )

        await db.delete(user)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Cannot delete this user — still referenced elsewhere in the system",
        )
    return {"message": "User deleted"}
