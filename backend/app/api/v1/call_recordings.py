"""Call recordings. Phones can't let an app record a call, so the telecaller's
phone records it with its own dialer and the mobile app uploads that file to
the call it just logged. The website plays it from the lead's timeline.

Files live on disk under RECORDINGS_DIR (a Docker volume in production); the
database row and the call activity's meta (recording_id) point at them."""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.deps import get_current_user
from ...db.session import get_db
from ...models.models import TeleCallRecording, TeleLeadActivity
from ...services.crm.timeutil import iso_utc, utcnow
from .crm import load_lead, require_scope

router = APIRouter(prefix="/crm", tags=["crm"])

MAX_BYTES = 60 * 1024 * 1024  # an hour of AMR/AAC is well under this
_CHUNK = 1024 * 1024

# What phone call recorders write, and how browsers should be told about it.
AUDIO_TYPES = {
    "m4a": "audio/mp4", "mp4": "audio/mp4", "aac": "audio/aac", "mp3": "audio/mpeg", "amr": "audio/amr",
    "awb": "audio/amr-wb", "3gp": "audio/3gpp", "wav": "audio/wav", "ogg": "audio/ogg", "opus": "audio/ogg",
}


def recordings_dir() -> Path:
    base = settings.RECORDINGS_DIR or str(Path(__file__).resolve().parents[3] / "data" / "recordings")
    return Path(base)


def recording_dict(r: TeleCallRecording) -> dict:
    return {"id": r.id, "activity_id": r.activity_id, "lead_id": r.lead_id, "mime_type": r.mime_type,
            "size_bytes": r.size_bytes, "duration_seconds": r.duration_seconds, "created_at": iso_utc(r.created_at)}


@router.post("/activities/{activity_id}/recording")
async def upload_recording(
    activity_id: int,
    file: UploadFile = File(...),
    duration_seconds: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    scope = await require_scope(db, user, "edit")
    act = (await db.execute(select(TeleLeadActivity).where(TeleLeadActivity.id == activity_id))).scalar_one_or_none()
    if not act:
        raise HTTPException(status_code=404, detail="Call not found")
    if act.type != "call":
        raise HTTPException(status_code=400, detail="Recordings belong to calls only")
    await load_lead(db, act.lead_id, scope)
    if act.user_id != user.id and not scope.is_admin:
        raise HTTPException(status_code=403, detail="Only the person who made the call can add its recording")

    # The app retries until it hears back: a second upload of the same call
    # keeps the first file.
    existing = (await db.execute(
        select(TeleCallRecording).where(TeleCallRecording.activity_id == act.id)
    )).scalar_one_or_none()
    if existing:
        return {"ok": True, "recording": recording_dict(existing)}

    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in AUDIO_TYPES:
        raise HTTPException(status_code=400, detail=f"Not a call recording (expected one of {sorted(AUDIO_TYPES)})")
    if duration_seconds is not None and not 0 <= duration_seconds <= 6 * 3600:
        raise HTTPException(status_code=400, detail="duration_seconds is out of range")

    now = utcnow()
    folder = recordings_dir() / f"{now:%Y}" / f"{now:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{act.lead_id}_{act.id}_{secrets.token_hex(4)}.{ext}"
    size = 0
    try:
        async with aiofiles.open(path, "wb") as out:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(status_code=413, detail="Recording is too large (60 MB max)")
                await out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The recording is empty")

    rec = TeleCallRecording(
        activity_id=act.id, lead_id=act.lead_id, user_id=user.id,
        file_path=str(path.relative_to(recordings_dir())), file_name=(file.filename or "")[:255],
        mime_type=AUDIO_TYPES[ext], size_bytes=size, duration_seconds=duration_seconds, created_at=now,
    )
    db.add(rec)
    await db.flush()
    # The timeline already returns the activity's meta, so this is all the
    # website needs to show a player on the call.
    act.meta = {**(act.meta or {}), "recording_id": rec.id}
    await db.commit()
    return {"ok": True, "recording": recording_dict(rec)}


@router.get("/recordings/{recording_id}/audio")
async def recording_audio(recording_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    scope = await require_scope(db, user)
    rec = (await db.execute(select(TeleCallRecording).where(TeleCallRecording.id == recording_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    await load_lead(db, rec.lead_id, scope)
    base = recordings_dir().resolve()
    path = (base / rec.file_path).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="The recording file is missing")
    return FileResponse(path, media_type=rec.mime_type or "application/octet-stream",
                        filename=f"call-{rec.lead_id}-{rec.activity_id}{path.suffix}")
