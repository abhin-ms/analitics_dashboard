from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from .config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    # Spaces around a password are a typing / keyboard accident, never meant:
    # every new password is saved without them (see verify_password).
    return bcrypt.hashpw(password.strip().encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Exactly as typed, else without the spaces a phone keyboard adds around
    it (a password saved before they were stripped still works as typed)."""
    hashed_b = hashed.encode("utf-8")
    if bcrypt.checkpw(plain.encode("utf-8"), hashed_b):
        return True
    return plain != plain.strip() and bcrypt.checkpw(plain.strip().encode("utf-8"), hashed_b)


def normalize_email(email: str | None) -> str:
    """Emails are matched without surrounding spaces and ignoring case."""
    return (email or "").strip().lower()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def session_claims(user) -> dict:
    """Claims every access/refresh token for this user carries: who it is
    and which session version it belongs to (see User.token_version)."""
    return {"sub": str(user.id), "tv": user.token_version or 0}


def token_matches_user(payload: dict, user) -> bool:
    """False once the user's sessions were ended (password changed,
    deactivated) after this token was issued. Tokens from before session
    versions existed carry no "tv" and count as version 0."""
    return int(payload.get("tv", 0) or 0) == (user.token_version or 0)


def create_password_reset_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    return jwt.encode({"sub": str(user_id), "exp": expire, "type": "password_reset"},
                      settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
