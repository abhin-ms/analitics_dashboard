"""AI Executive Summary endpoints."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...core.deps import get_db, get_current_user, get_user_permissions, require_permission
from ...core.store_scope import ALWAYS_SEE_ALL_ROLES
from ...models.models import User, Role, AISummaryConfig
from ...services.ai_summary_service import get_summary, generate_summary, get_or_create_config, DEFAULT_SYSTEM_PROMPT, DEFAULT_MODEL
from ...services.ai_section_contexts import SECTION_VIEW_RESOURCE, SECTION_DEFAULT_PROMPTS
from ...services.dashboard_chat_service import ask_dashboard_chat, get_chat_usage_summary

router = APIRouter(prefix="/ai-analytics", tags=["ai-analytics"])

MANAGE_ROLES = {"SuperAdmin", "Admin", "CEO"}

KNOWN_SECTIONS = set(SECTION_VIEW_RESOURCE.keys()) | {"overview"}


async def require_ai_manage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    perms = await get_user_permissions(user, db)
    if any(p["resource"] == "ai_analytics" and p["action"] == "manage" for p in perms):
        return user
    role_name = (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none() or ""
    if role_name in MANAGE_ROLES:
        return user
    raise HTTPException(status_code=403, detail="Missing permission: ai_analytics:manage")


async def _check_view(section: str, user: User, db: AsyncSession) -> None:
    if section not in KNOWN_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    # Summaries and chat are built from company-wide figures, so only roles
    # that see every store may read them — a section's view permission alone
    # isn't enough (every role holds dashboard:view).
    role_name = (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none() or ""
    if role_name not in ALWAYS_SEE_ALL_ROLES:
        raise HTTPException(status_code=403, detail="AI analytics covers every store and is limited to company-wide roles")
    if role_name in MANAGE_ROLES:
        return
    resource = SECTION_VIEW_RESOURCE.get(section, "dashboard")
    perms = await get_user_permissions(user, db)
    if any(p["resource"] == resource and p["action"] == "view" for p in perms):
        return
    raise HTTPException(status_code=403, detail=f"Missing permission: {resource}:view")


def _month(month: str = None) -> str:
    return month or date.today().strftime("%Y-%m")


@router.get("/summary")
async def ai_summary(
    section: str = "overview",
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _check_view(section, user, db)
    return await get_summary(db, _month(month), section=section)


@router.post("/summary/regenerate")
async def ai_summary_regenerate(
    section: str = "overview",
    month: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_ai_manage),
):
    return await generate_summary(db, _month(month), section=section, force=True, user_id=user.id)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)


@router.post("/chat")
async def dashboard_chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _check_view("overview", user, db)
    return await ask_dashboard_chat(
        db, user.id, body.message,
        [{"role": m.role, "content": m.content} for m in body.history],
    )


@router.get("/chat/usage")
async def dashboard_chat_usage(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_ai_manage),
):
    return await get_chat_usage_summary(db, days)


class AISummaryConfigUpdate(BaseModel):
    system_prompt: str = Field(default="", max_length=20000)
    provider: str = Field(default="claude", pattern="^(claude|openai)$")
    model_name: str = Field(default="", max_length=100)


@router.get("/config")
async def ai_config(
    section: str = "overview",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_ai_manage),
):
    if section not in KNOWN_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    config = await get_or_create_config(db, section)
    return {
        "id": config.id,
        "name": config.name,
        "system_prompt": config.system_prompt or SECTION_DEFAULT_PROMPTS.get(section, DEFAULT_SYSTEM_PROMPT),
        "provider": config.provider,
        "model_name": config.model_name or DEFAULT_MODEL,
        "is_active": config.is_active,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


@router.put("/config")
async def ai_config_update(
    body: AISummaryConfigUpdate,
    section: str = "overview",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_ai_manage),
):
    if section not in KNOWN_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    config = await get_or_create_config(db, section)
    if body.system_prompt:
        config.system_prompt = body.system_prompt
    config.provider = body.provider
    config.model_name = body.model_name or DEFAULT_MODEL
    config.updated_by = user.id
    await db.commit()
    await db.refresh(config)
    return {
        "id": config.id,
        "name": config.name,
        "system_prompt": config.system_prompt,
        "provider": config.provider,
        "model_name": config.model_name,
        "is_active": config.is_active,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
