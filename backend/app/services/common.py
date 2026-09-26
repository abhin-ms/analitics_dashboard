import secrets

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.security import hash_password
from ..models.models import User, Role

_DEFAULT_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


async def _get_or_create_role(db: AsyncSession, name: str) -> Role:
    result = await db.execute(select(Role).where(Role.name == name))
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name=name, description=f"{name} role")
        db.add(role)
        await db.flush()
    return role


async def get_or_create_unassigned_tl(db: AsyncSession) -> User:
    """The inactive 'Unassigned' placeholder Team Leader that
    Store.team_leader_id (NOT NULL) gets reassigned to whenever a real Team
    Leader's stores need a home — used by the MCP/Sheets sync services when
    auto-creating a store with no known owner, and by user deletion when the
    Team Leader being deleted still owns stores."""
    role = await _get_or_create_role(db, "Team Leader")
    result = await db.execute(select(User).where(User.name.ilike("Unassigned")))
    user = result.scalar_one_or_none()
    if user:
        return user
    email = "unassigned@system.local"
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            name="Unassigned", email=email, password_hash=_DEFAULT_PASSWORD_HASH,
            role_id=role.id, is_active=False,
        )
        db.add(user)
        await db.flush()
    return user


async def get_or_create_unassigned_store(db: AsyncSession):
    """The inactive 'Unassigned (Instagram)' placeholder Store that
    Lead.store_id (NOT NULL) falls back to when a lead is captured with no
    specific store context yet — e.g. an Instagram account not linked to a
    real store. Leads created after the account IS linked use the real
    store instead; this only covers the gap before that's set up. Without
    this fallback, every Instagram lead capture attempt on an unlinked
    account would fail outright on the NOT NULL constraint."""
    from ..models.models import Store
    result = await db.execute(select(Store).where(Store.name == "Unassigned (Instagram)"))
    store = result.scalar_one_or_none()
    if store:
        return store
    tl = await get_or_create_unassigned_tl(db)
    store = Store(
        name="Unassigned (Instagram)", team_leader_id=tl.id,
        is_active=False, country="India",
    )
    db.add(store)
    await db.flush()
    return store
