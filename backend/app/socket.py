import logging
import socketio
from .core.security import decode_token
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
    if not payload:
        raise socketio.exceptions.ConnectionRefusedError("Invalid token")
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
