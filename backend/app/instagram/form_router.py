from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime

from ..db.session import get_db
from ..core.deps import require_permission
from ..core.config import settings
from ..models.models import User, Store
from .form_models import IGForm, IGFormField, IGFormSubmission
from .form_schemas import (
    IGFormCreate, IGFormUpdate, IGFormResponse, IGFormFieldResponse,
    IGFormUpdateFields, IGFormSubmissionResponse, IGFormPhase2Submit,
)

router = APIRouter(prefix="/instagram", tags=["instagram-forms"])


# ── Forms CRUD ───────────────────────────────────────────────────
@router.get("/forms", response_model=list[IGFormResponse])
async def list_forms(
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGForm).order_by(IGForm.id))
    forms = result.scalars().all()
    resp = []
    for f in forms:
        count_result = await db.execute(
            select(func.count(IGFormSubmission.id)).where(IGFormSubmission.form_id == f.id)
        )
        count = count_result.scalar() or 0
        form_resp = IGFormResponse(
            id=f.id, name=f.name, display_name=f.display_name,
            description=f.description, form_type=f.form_type,
            ai_prompt_hint=f.ai_prompt_hint, success_message=f.success_message,
            is_active=f.is_active, created_at=f.created_at, submission_count=count,
        )
        fields_result = await db.execute(
            select(IGFormField).where(IGFormField.form_id == f.id).order_by(IGFormField.sort_order)
        )
        form_resp.fields = [IGFormFieldResponse.model_validate(field) for field in fields_result.scalars().all()]
        resp.append(form_resp)
    return resp


@router.post("/forms", response_model=IGFormResponse)
async def create_form(
    body: IGFormCreate,
    _user: User = require_permission("instagram", "create"),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(IGForm).where(IGForm.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Form with this name already exists")

    form = IGForm(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        form_type=body.form_type,
        ai_prompt_hint=body.ai_prompt_hint,
        success_message=body.success_message,
        is_active=body.is_active,
    )
    db.add(form)
    await db.flush()

    for i, field_data in enumerate(body.fields):
        field = IGFormField(
            form_id=form.id,
            field_key=field_data.field_key,
            label=field_data.label,
            field_type=field_data.field_type,
            required=field_data.required,
            options=field_data.options,
            placeholder=field_data.placeholder,
            phase=field_data.phase,
            sort_order=field_data.sort_order or i,
            ai_extract_hint=field_data.ai_extract_hint,
        )
        db.add(field)

    await db.commit()
    await db.refresh(form)

    fields_result = await db.execute(
        select(IGFormField).where(IGFormField.form_id == form.id).order_by(IGFormField.sort_order)
    )
    form_fields = [IGFormFieldResponse.model_validate(f) for f in fields_result.scalars().all()]

    return IGFormResponse(
        id=form.id, name=form.name, display_name=form.display_name,
        description=form.description, form_type=form.form_type,
        ai_prompt_hint=form.ai_prompt_hint, success_message=form.success_message,
        is_active=form.is_active, fields=form_fields, created_at=form.created_at,
    )


@router.put("/forms/{form_id}", response_model=IGFormResponse)
async def update_form(
    form_id: int,
    body: IGFormUpdate,
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGForm).where(IGForm.id == form_id))
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(404, "Form not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(form, field, value)

    await db.commit()
    await db.refresh(form)

    fields_result = await db.execute(
        select(IGFormField).where(IGFormField.form_id == form.id).order_by(IGFormField.sort_order)
    )
    form_fields = [IGFormFieldResponse.model_validate(f) for f in fields_result.scalars().all()]

    count_result = await db.execute(
        select(func.count(IGFormSubmission.id)).where(IGFormSubmission.form_id == form.id)
    )
    count = count_result.scalar() or 0

    return IGFormResponse(
        id=form.id, name=form.name, display_name=form.display_name,
        description=form.description, form_type=form.form_type,
        ai_prompt_hint=form.ai_prompt_hint, success_message=form.success_message,
        is_active=form.is_active, fields=form_fields, submission_count=count,
        created_at=form.created_at,
    )


@router.delete("/forms/{form_id}")
async def delete_form(
    form_id: int,
    _user: User = require_permission("instagram", "delete"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGForm).where(IGForm.id == form_id))
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(404, "Form not found")
    await db.delete(form)
    await db.commit()
    return {"detail": "Form deleted"}


@router.put("/forms/{form_id}/fields", response_model=list[IGFormFieldResponse])
async def update_form_fields(
    form_id: int,
    body: IGFormUpdateFields,
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGForm).where(IGForm.id == form_id))
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(404, "Form not found")

    existing_result = await db.execute(
        select(IGFormField).where(IGFormField.form_id == form_id)
    )
    for field in existing_result.scalars().all():
        await db.delete(field)

    new_fields = []
    for i, field_data in enumerate(body.fields):
        field = IGFormField(
            form_id=form_id,
            field_key=field_data.field_key,
            label=field_data.label,
            field_type=field_data.field_type,
            required=field_data.required,
            options=field_data.options,
            placeholder=field_data.placeholder,
            phase=field_data.phase,
            sort_order=field_data.sort_order or i,
            ai_extract_hint=field_data.ai_extract_hint,
        )
        db.add(field)
        new_fields.append(field)

    await db.commit()
    return [IGFormFieldResponse.model_validate(f) for f in new_fields]


# ── Submissions ──────────────────────────────────────────────────
@router.get("/forms/{form_id}/submissions", response_model=list[IGFormSubmissionResponse])
async def list_submissions(
    form_id: int,
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    query = select(IGFormSubmission).where(IGFormSubmission.form_id == form_id)
    if status:
        query = query.where(IGFormSubmission.status == status)
    query = query.order_by(IGFormSubmission.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    submissions = result.scalars().all()

    form_result = await db.execute(select(IGForm).where(IGForm.id == form_id))
    form = form_result.scalar_one_or_none()
    form_name = form.display_name if form else ""

    return [
        IGFormSubmissionResponse(
            id=s.id, form_id=s.form_id, form_name=form_name,
            conversation_id=s.conversation_id, ig_user_id=s.ig_user_id,
            phase1_data=s.phase1_data or {}, phase2_data=s.phase2_data or {},
            status=s.status, lead_id=s.lead_id,
            created_at=s.created_at, updated_at=s.updated_at,
        )
        for s in submissions
    ]


@router.get("/submissions", response_model=list[IGFormSubmissionResponse])
async def list_all_submissions(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    query = select(IGFormSubmission)
    if status:
        query = query.where(IGFormSubmission.status == status)
    query = query.order_by(IGFormSubmission.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    submissions = result.scalars().all()

    resp = []
    for s in submissions:
        form_result = await db.execute(select(IGForm).where(IGForm.id == s.form_id))
        form = form_result.scalar_one_or_none()
        resp.append(IGFormSubmissionResponse(
            id=s.id, form_id=s.form_id, form_name=form.display_name if form else "",
            conversation_id=s.conversation_id, ig_user_id=s.ig_user_id,
            phase1_data=s.phase1_data or {}, phase2_data=s.phase2_data or {},
            status=s.status, lead_id=s.lead_id,
            created_at=s.created_at, updated_at=s.updated_at,
        ))
    return resp


# ── Public: hosted page (no login; the link token is the credential) ─
MAX_PHASE2_VALUE_LEN = 500


async def _public_submission(db: AsyncSession, form_id: int, token: str) -> IGFormSubmission:
    result = await db.execute(
        select(IGFormSubmission).where(
            IGFormSubmission.public_token == token,
            IGFormSubmission.form_id == form_id,
        )
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise HTTPException(404, "Submission not found")
    return submission


async def _phase2_fields(db: AsyncSession, form_id: int) -> list[IGFormField]:
    result = await db.execute(
        select(IGFormField).where(IGFormField.form_id == form_id, IGFormField.phase == 2)
        .order_by(IGFormField.sort_order)
    )
    return list(result.scalars().all())


def clean_phase2(fields: list[IGFormField], data: dict) -> dict:
    """Keep only the form's phase-2 fields, as bounded strings; enforce
    required fields and select options."""
    by_key = {f.field_key: f for f in fields}
    unknown = set(data) - set(by_key)
    if unknown:
        raise HTTPException(422, f"Unknown fields: {', '.join(sorted(unknown))}")
    cleaned = {}
    for key, field in by_key.items():
        value = data.get(key)
        if value is None or value == "":
            if field.required:
                raise HTTPException(422, f"{field.label} is required")
            continue
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise HTTPException(422, f"{field.label} must be text")
        value = str(value).strip()
        if len(value) > MAX_PHASE2_VALUE_LEN:
            raise HTTPException(422, f"{field.label} is too long")
        if field.field_type in ("select", "dropdown") and field.options:
            allowed = {str(o.get("value")) if isinstance(o, dict) else str(o) for o in field.options}
            if value not in allowed:
                raise HTTPException(422, f"{field.label}: invalid option")
        cleaned[key] = value
    return cleaned


@router.post("/forms/{form_id}/submit")
async def submit_phase2(
    form_id: int,
    body: IGFormPhase2Submit,
    token: str = Query(..., min_length=16, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    submission = await _public_submission(db, form_id, token)
    if submission.status == "completed":
        return {"detail": "Already completed", "status": "completed"}

    submission.phase2_data = clean_phase2(await _phase2_fields(db, form_id), body.phase2_data)
    submission.status = "completed"
    await db.commit()

    return {"detail": "Booking completed", "status": "completed"}


@router.get("/forms/{form_id}/public")
async def get_public_form(
    form_id: int,
    token: str = Query(..., min_length=16, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    form_result = await db.execute(select(IGForm).where(IGForm.id == form_id))
    form = form_result.scalar_one_or_none()
    if not form:
        raise HTTPException(404, "Form not found")

    submission = await _public_submission(db, form_id, token)

    phase2_fields = [
        {
            "field_key": f.field_key,
            "label": f.label,
            "field_type": f.field_type,
            "required": f.required,
            "options": f.options or [],
            "placeholder": f.placeholder,
        }
        for f in await _phase2_fields(db, form_id)
    ]

    stores_result = await db.execute(select(Store.id, Store.name).where(Store.is_active == True))
    branches = [{"id": s.id, "name": s.name} for s in stores_result.all()]

    return {
        "form_name": form.display_name,
        "phase1_data": submission.phase1_data or {},
        "phase2_fields": phase2_fields,
        "branches": branches,
        "status": submission.status,
    }
