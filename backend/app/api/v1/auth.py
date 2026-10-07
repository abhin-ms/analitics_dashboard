from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ...core.config import settings
from ...core.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, decode_token, session_claims, token_matches_user,
    create_password_reset_token,
)
from ...core.deps import get_db, get_current_user, get_user_permissions
from ...models.models import User, Role
from ...schemas import (
    LoginRequest, TokenResponse, PasswordResetRequest,
    SetPasswordRequest, UserMeResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    # Sliding session: every refresh re-issues the cookie with a fresh
    # REFRESH_TOKEN_EXPIRE_DAYS (90 by default), so anyone who opens the
    # dashboard at least that often stays signed in until they log out.
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    claims = session_claims(user)
    _set_refresh_cookie(response, create_refresh_token(claims))
    return TokenResponse(access_token=create_access_token(claims))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not token_matches_user(payload, user):
        response.delete_cookie("refresh_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session ended — please sign in again")

    claims = session_claims(user)
    _set_refresh_cookie(response, create_refresh_token(claims))
    return TokenResponse(access_token=create_access_token(claims))


@router.get("/me", response_model=UserMeResponse)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    perms = await get_user_permissions(user, db)
    store_ids = [sa.store_id for sa in user.store_access]
    result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = result.scalar_one_or_none()
    return UserMeResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role_id=user.role_id,
        role_name=role.name if role else "",
        is_active=user.is_active,
        permissions=perms,
        store_ids=store_ids,
    )


@router.post("/logout")
async def logout(response: Response):
    # Signs out this browser only (like Facebook/Instagram); other devices
    # stay signed in. Password changes and deactivation end every session.
    response.delete_cookie("refresh_token", httponly=True, secure=settings.SECURE_COOKIES, samesite="lax")
    return {"message": "Logged out"}


@router.post("/forgot-password")
async def forgot_password(body: PasswordResetRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user:
        token = create_password_reset_token(user.id)
        user.invite_token = token
        user.invite_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        await db.commit()
    return {"message": "If the email exists, a reset link has been generated"}


@router.post("/set-password")
async def set_password(body: SetPasswordRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.token)
    if not payload or payload.get("type") != "password_reset":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found")
    # Single use: only the link most recently issued for this user works.
    if user.invite_token != body.token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link has already been used or replaced")

    user.password_hash = hash_password(body.new_password)
    user.invite_token = None
    user.invite_expires_at = None
    user.token_version = (user.token_version or 0) + 1  # sign out every device
    await db.commit()
    return {"message": "Password updated"}
