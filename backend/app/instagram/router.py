from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from typing import Optional
from datetime import datetime, timedelta

from ..db.session import get_db
from ..core.deps import require_permission, get_current_user
from ..models.models import User
from .models import (
    IGAccount, IGConversation, IGMessage, IGComment,
    IGCommentRule, AIProvider, AIUsageLog, IGBotSettings,
)
from .schemas import (
    IGAccountCreate, IGAccountUpdate, IGAccountResponse,
    IGConversationResponse, IGMessageResponse, IGConversationAssign,
    IGCommentRuleCreate, IGCommentRuleUpdate, IGCommentRuleResponse,
    IGBotSettingsUpdate, IGBotSettingsResponse,
    AIProviderUpdate, AIProviderToggle, AIProviderResponse,
    IGStatsResponse, IGCommentResponse,
)
from .utils import encrypt_token, decrypt_token

router = APIRouter(prefix="/instagram", tags=["instagram"])


# ── Accounts ─────────────────────────────────────────────────────
@router.get("/accounts", response_model=list[IGAccountResponse])
async def list_accounts(
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGAccount))
    accounts = result.scalars().all()
    resp = []
    for a in accounts:
        store_name = ""
        if a.store:
            store_name = a.store.name
        resp.append(IGAccountResponse(
            id=a.id, ig_user_id=a.ig_user_id, page_id=a.page_id,
            page_name=a.page_name, store_id=a.store_id,
            store_name=store_name, is_active=a.is_active,
            created_at=a.created_at,
        ))
    return resp


@router.post("/accounts", response_model=IGAccountResponse)
async def create_account(
    body: IGAccountCreate,
    _user: User = require_permission("instagram", "create"),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(IGAccount).where(IGAccount.ig_user_id == body.ig_user_id))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Instagram account already connected")

    account = IGAccount(
        ig_user_id=body.ig_user_id,
        page_id=body.page_id,
        page_name=body.page_name,
        access_token_encrypted=encrypt_token(body.access_token),
        store_id=body.store_id,
    )
    db.add(account)
    await db.flush()

    bot_settings = IGBotSettings(ig_account_id=account.id)
    db.add(bot_settings)
    await db.commit()
    await db.refresh(account)

    return IGAccountResponse(
        id=account.id, ig_user_id=account.ig_user_id, page_id=account.page_id,
        page_name=account.page_name, store_id=account.store_id, is_active=account.is_active,
        created_at=account.created_at,
    )


@router.put("/accounts/{account_id}", response_model=IGAccountResponse)
async def update_account(
    account_id: int,
    body: IGAccountUpdate,
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGAccount).where(IGAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(404, "Account not found")

    if body.page_name is not None:
        account.page_name = body.page_name
    if body.access_token is not None:
        account.access_token_encrypted = encrypt_token(body.access_token)
    if body.store_id is not None:
        account.store_id = body.store_id
    if body.is_active is not None:
        account.is_active = body.is_active

    await db.commit()
    await db.refresh(account)

    return IGAccountResponse(
        id=account.id, ig_user_id=account.ig_user_id, page_id=account.page_id,
        page_name=account.page_name, store_id=account.store_id, is_active=account.is_active,
        created_at=account.created_at,
    )


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int,
    _user: User = require_permission("instagram", "delete"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGAccount).where(IGAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(404, "Account not found")

    await db.delete(account)
    await db.commit()
    return {"detail": "Account disconnected"}


# ── Conversations ────────────────────────────────────────────────
@router.get("/conversations", response_model=list[IGConversationResponse])
async def list_conversations(
    status: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    ig_account_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    query = select(IGConversation)
    if status:
        query = query.where(IGConversation.status == status)
    if assigned_to:
        query = query.where(IGConversation.assigned_to == assigned_to)
    if ig_account_id:
        query = query.where(IGConversation.ig_account_id == ig_account_id)
    query = query.order_by(desc(IGConversation.last_message_at)).offset(offset).limit(limit)

    result = await db.execute(query)
    conversations = result.scalars().all()

    resp = []
    for c in conversations:
        msg_count_result = await db.execute(
            select(func.count(IGMessage.id)).where(IGMessage.conversation_id == c.id)
        )
        msg_count = msg_count_result.scalar() or 0

        assignee_name = ""
        if c.assignee:
            assignee_name = c.assignee.name

        resp.append(IGConversationResponse(
            id=c.id, ig_account_id=c.ig_account_id, ig_user_id=c.ig_user_id,
            customer_name=c.customer_name, status=c.status, assigned_to=c.assigned_to,
            assignee_name=assignee_name, lead_id=c.lead_id,
            last_message_at=c.last_message_at, message_count=msg_count,
            created_at=c.created_at,
        ))
    return resp


@router.get("/conversations/{conv_id}", response_model=list[IGMessageResponse])
async def get_conversation_messages(
    conv_id: int,
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IGMessage).where(IGMessage.conversation_id == conv_id).order_by(IGMessage.created_at)
    )
    messages = result.scalars().all()
    return [
        IGMessageResponse(
            id=m.id, conversation_id=m.conversation_id, direction=m.direction,
            message_type=m.message_type, content=m.content, ig_message_id=m.ig_message_id,
            ai_provider=m.ai_provider, ai_input_tokens=m.ai_input_tokens,
            ai_output_tokens=m.ai_output_tokens, created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/conversations/{conv_id}/assign")
async def assign_conversation(
    conv_id: int,
    body: IGConversationAssign,
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGConversation).where(IGConversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    conv.assigned_to = body.assigned_to
    await db.commit()
    return {"detail": "Assigned"}


# ── Comment Rules ────────────────────────────────────────────────
@router.get("/comments/rules", response_model=list[IGCommentRuleResponse])
async def list_comment_rules(
    ig_account_id: Optional[int] = Query(None),
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    query = select(IGCommentRule)
    if ig_account_id:
        query = query.where(IGCommentRule.ig_account_id == ig_account_id)
    query = query.order_by(IGCommentRule.priority.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/comments/rules", response_model=IGCommentRuleResponse)
async def create_comment_rule(
    body: IGCommentRuleCreate,
    ig_account_id: int = Query(...),
    _user: User = require_permission("instagram", "create"),
    db: AsyncSession = Depends(get_db),
):
    rule = IGCommentRule(
        ig_account_id=ig_account_id,
        name=body.name,
        rule_type=body.rule_type,
        trigger_words=body.trigger_words,
        action=body.action,
        reply_template=body.reply_template,
        ai_prompt=body.ai_prompt,
        is_active=body.is_active,
        priority=body.priority,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.put("/comments/rules/{rule_id}", response_model=IGCommentRuleResponse)
async def update_comment_rule(
    rule_id: int,
    body: IGCommentRuleUpdate,
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGCommentRule).where(IGCommentRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Rule not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/comments/rules/{rule_id}")
async def delete_comment_rule(
    rule_id: int,
    _user: User = require_permission("instagram", "delete"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IGCommentRule).where(IGCommentRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Rule not found")
    await db.delete(rule)
    await db.commit()
    return {"detail": "Rule deleted"}


# ── Bot Settings ─────────────────────────────────────────────────
@router.get("/settings", response_model=IGBotSettingsResponse)
async def get_bot_settings(
    ig_account_id: int = Query(...),
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IGBotSettings).where(IGBotSettings.ig_account_id == ig_account_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = IGBotSettings(ig_account_id=ig_account_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.put("/settings", response_model=IGBotSettingsResponse)
async def update_bot_settings(
    body: IGBotSettingsUpdate,
    ig_account_id: int = Query(...),
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IGBotSettings).where(IGBotSettings.ig_account_id == ig_account_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = IGBotSettings(ig_account_id=ig_account_id)
        db.add(settings)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)
    return settings


# ── AI Providers ─────────────────────────────────────────────────
@router.get("/ai-providers", response_model=list[AIProviderResponse])
async def list_ai_providers(
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AIProvider))
    return result.scalars().all()


@router.put("/ai-providers/{provider_id}", response_model=AIProviderResponse)
async def update_ai_provider(
    provider_id: int,
    body: AIProviderUpdate,
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AIProvider).where(AIProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(404, "Provider not found")

    if body.api_key is not None:
        provider.api_key_encrypted = encrypt_token(body.api_key)
    if body.model_name is not None:
        provider.model_name = body.model_name

    await db.commit()
    await db.refresh(provider)
    return provider


@router.post("/ai-providers/{provider_id}/toggle", response_model=AIProviderResponse)
async def toggle_ai_provider(
    provider_id: int,
    body: AIProviderToggle,
    _user: User = require_permission("instagram", "edit"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AIProvider).where(AIProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(404, "Provider not found")

    if body.is_active:
        all_result = await db.execute(select(AIProvider))
        for p in all_result.scalars().all():
            if p.id != provider_id:
                p.is_active = False

    provider.is_active = body.is_active
    await db.commit()
    await db.refresh(provider)
    return provider


# ── Stats ────────────────────────────────────────────────────────
@router.get("/stats", response_model=IGStatsResponse)
async def get_instagram_stats(
    ig_account_id: Optional[int] = Query(None),
    days: int = Query(30, le=90),
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)

    conv_query = select(IGConversation)
    if ig_account_id:
        conv_query = conv_query.where(IGConversation.ig_account_id == ig_account_id)

    total_conv = (await db.execute(
        select(func.count(IGConversation.id)).select_from(conv_query.subquery())
    )).scalar() or 0

    active_conv = (await db.execute(
        select(func.count(IGConversation.id)).select_from(
            conv_query.where(IGConversation.status == "active").subquery()
        )
    )).scalar() or 0

    msg_query = select(IGMessage).where(IGMessage.created_at >= since)
    if ig_account_id:
        msg_query = msg_query.join(IGConversation).where(IGConversation.ig_account_id == ig_account_id)

    total_msgs = (await db.execute(
        select(func.count(IGMessage.id)).select_from(msg_query.subquery())
    )).scalar() or 0

    sent_msgs = (await db.execute(
        select(func.count(IGMessage.id)).select_from(
            msg_query.where(IGMessage.direction == "outbound").subquery()
        )
    )).scalar() or 0

    received_msgs = (await db.execute(
        select(func.count(IGMessage.id)).select_from(
            msg_query.where(IGMessage.direction == "inbound").subquery()
        )
    )).scalar() or 0

    ai_resp = (await db.execute(
        select(func.count(IGMessage.id)).select_from(
            msg_query.where(IGMessage.ai_provider.isnot(None)).subquery()
        )
    )).scalar() or 0

    lead_query = select(func.count(Lead.id))
    if ig_account_id:
        lead_query = lead_query.where(Lead.source == "instagram")
    leads_generated = (await db.execute(lead_query)).scalar() or 0

    usage_query = select(AIUsageLog).where(AIUsageLog.created_at >= since)
    if ig_account_id:
        usage_query = usage_query.where(AIUsageLog.ig_account_id == ig_account_id)
    usage_result = await db.execute(usage_query)
    usage_logs = usage_result.scalars().all()

    credits_used = {}
    for log in usage_logs:
        provider_name = log.ai_provider.provider if log.ai_provider else "unknown"
        if provider_name not in credits_used:
            credits_used[provider_name] = {"input_tokens": 0, "output_tokens": 0, "cost": 0, "calls": 0}
        credits_used[provider_name]["input_tokens"] += log.input_tokens
        credits_used[provider_name]["output_tokens"] += log.output_tokens
        credits_used[provider_name]["cost"] += float(log.cost_estimate or 0)
        credits_used[provider_name]["calls"] += 1

    return IGStatsResponse(
        total_conversations=total_conv,
        active_conversations=active_conv,
        total_messages=total_msgs,
        messages_sent=sent_msgs,
        messages_received=received_msgs,
        ai_responses=ai_resp,
        leads_generated=leads_generated,
        credits_used=credits_used,
    )


@router.get("/usage-by-customer")
async def get_usage_by_customer(
    ig_account_id: Optional[int] = Query(None),
    days: int = Query(30, le=90),
    _user: User = require_permission("instagram", "view"),
    db: AsyncSession = Depends(get_db),
):
    """Real token/cost spend per Instagram customer — answers "which
    conversations are actually costing money" instead of only a single
    company-wide total, by joining each usage log back to the conversation
    it was generated for."""
    since = datetime.utcnow() - timedelta(days=days)

    query = (
        select(
            IGConversation.id,
            IGConversation.customer_name,
            IGConversation.ig_user_id,
            func.count(AIUsageLog.id),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.cost_estimate), 0),
        )
        .join(AIUsageLog, AIUsageLog.conversation_id == IGConversation.id)
        .where(AIUsageLog.created_at >= since)
        .group_by(IGConversation.id, IGConversation.customer_name, IGConversation.ig_user_id)
        .order_by(func.sum(AIUsageLog.cost_estimate).desc())
    )
    if ig_account_id:
        query = query.where(IGConversation.ig_account_id == ig_account_id)

    rows = (await db.execute(query)).all()
    return [
        {
            "conversation_id": conv_id,
            "customer_name": name or "",
            "ig_user_id": ig_user_id,
            "ai_replies": replies,
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "total_tokens": int(in_tok) + int(out_tok),
            "cost_usd": round(float(cost), 6),
        }
        for conv_id, name, ig_user_id, replies, in_tok, out_tok, cost in rows
    ]
