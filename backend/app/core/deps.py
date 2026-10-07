from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from .config import settings
from .security import decode_token, token_matches_user
from ..db.session import get_db
from ..models.models import User, Role, Permission, RolePermission, UserStoreAccess

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(
        select(User)
        .where(User.id == int(user_id))
        .options(selectinload(User.store_access))
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    if not token_matches_user(payload, user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session ended — please sign in again")
    return user


async def get_user_permissions(user: User, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Permission.resource, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == user.role_id)
    )
    return [{"resource": r.resource, "action": r.action} for r in result.all()]


def require_permission(resource: str, action: str):
    async def dependency(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        perms = await get_user_permissions(user, db)
        if not any(p["resource"] == resource and p["action"] == action for p in perms):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {resource}:{action}",
            )
        return user
    return Depends(dependency)


ADMIN_TIER_ROLES = {"SuperAdmin", "Admin", "CEO", "COO", "Regional Manager"}


def require_admin_tier():
    """Restricts to company-wide/admin-tier roles. Team Leader, Telecaller,
    Salesperson, Store Staff, and Viewer all have their own scoped
    dashboards and must never reach a company-wide report endpoint just
    because they hold the generic "dashboard:view" permission — that
    permission only gates whether a role has a dashboard at all, not
    whether it should see every branch/country in the company.
    """
    async def dependency(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        role_name = (
            await db.execute(select(Role.name).where(Role.id == user.role_id))
        ).scalar_one_or_none()
        if role_name not in ADMIN_TIER_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This report is only available to admin-tier roles",
            )
        return user
    return Depends(dependency)
