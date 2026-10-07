import logging
import socketio
from sqlalchemy import select
from .core.security import decode_token, token_matches_user
from .core.config import settings

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.cors_origins_list,
    logger=False,
    engineio_logger=False,
)


@sio.event
async def connect(sid, environ, auth):
    token = auth.get("token") if auth else None
    if not token:
        raise socketio.exceptions.ConnectionRefusedError("Authentication required")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access" or not payload.get("sub"):
        # Expired pass: the client renews it and reconnects on its own.
        raise socketio.exceptions.ConnectionRefusedError("Invalid token")
    from .db.session import AsyncSessionLocal
    from .models.models import User
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == int(payload["sub"])))).scalar_one_or_none()
    if not user or not user.is_active or not token_matches_user(payload, user):
        raise socketio.exceptions.ConnectionRefusedError("Session ended")
    await sio.save_session(sid, {
        "user_id": payload.get("sub"),
        "role": payload.get("role"),
    })
    # Per-user room so CRM alerts reach only their recipient. The existing
    # broadcast ("data:refresh") still goes to everyone as before.
    if payload.get("sub"):
        await sio.enter_room(sid, f"user:{payload.get('sub')}")
    logger.info(f"[Socket.IO] Client connected: {sid}")


@sio.event
async def disconnect(sid):
    logger.info(f"[Socket.IO] Client disconnected: {sid}")
