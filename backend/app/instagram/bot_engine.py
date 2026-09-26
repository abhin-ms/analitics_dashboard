import logging
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from .models import (
    IGAccount, IGConversation, IGMessage, IGBotSettings,
    AIProvider, AIUsageLog, IGComment, IGCommentRule, IGFAQ,
)
from .form_models import IGForm, IGFormField, IGFormSubmission
from .graph_client import InstagramGraphClient
from .ai_service import ai_service, build_system_prompt, AIResponse
from .utils import decrypt_token
from ..models.models import Lead, Store, StoreMcpAlias
from ..core.config import settings

logger = logging.getLogger(__name__)


def _normalize_text(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


# Simple phone-shape check used only as a last resort if the AI's own
# extraction misses one — the AI extracting it directly (ROUTE_CONVERSATION_TOOL's
# extracted_phone field) is the primary, more reliable path.
_PHONE_RE = re.compile(r"(\+?\d[\d\s-]{7,}\d)")


class BotEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_provider(self) -> tuple[AIProvider, str] | None:
        result = await self.db.execute(
            select(AIProvider).where(AIProvider.is_active == True)
        )
        provider = result.scalar_one_or_none()
        if not provider:
            return None
        api_key = decrypt_token(provider.api_key_encrypted)
        return provider, api_key

    async def _get_active_forms(self, ig_account_id: int) -> list[dict]:
        result = await self.db.execute(
            select(IGForm).where(
                IGForm.ig_account_id == ig_account_id, IGForm.is_active == True
            )
        )
        forms = result.scalars().all()
        active_forms = []
        for form in forms:
            fields_result = await self.db.execute(
                select(IGFormField).where(
                    IGFormField.form_id == form.id, IGFormField.phase == 1
                ).order_by(IGFormField.sort_order)
            )
            fields = fields_result.scalars().all()
            active_forms.append({
                "slug": form.name,
                "description": form.ai_prompt_hint or form.display_name,
                "field_keys": [f.field_key for f in fields],
            })
        return active_forms

    async def _get_active_faqs(self, ig_account_id: int) -> list[dict]:
        result = await self.db.execute(
            select(IGFAQ).where(
                IGFAQ.ig_account_id == ig_account_id,
                IGFAQ.is_active == True,
            ).order_by(IGFAQ.priority.desc()).limit(10)
        )
        faqs = result.scalars().all()
        return [
            {"question": faq.question, "answer": faq.answer, "keywords": faq.keywords or []}
            for faq in faqs
        ]

    async def _get_triggered_forms(self, conversation_id: int) -> list[str]:
        result = await self.db.execute(
            select(IGForm.name).join(
                IGFormSubmission, IGFormSubmission.form_id == IGForm.id
            ).where(
                IGFormSubmission.conversation_id == conversation_id,
                IGFormSubmission.status.in_(["partial", "completed"]),
            )
        )
        return [row[0] for row in result.all()]

    async def _get_active_submission(self, conversation_id: int) -> IGFormSubmission | None:
        result = await self.db.execute(
            select(IGFormSubmission).where(
                IGFormSubmission.conversation_id == conversation_id,
                IGFormSubmission.status == "partial",
            )
        )
        return result.scalar_one_or_none()

    async def _process_form_answer(
        self, conversation: IGConversation, message_text: str,
        client: InstagramGraphClient, sender_id: str,
    ):
        submission = await self._get_active_submission(conversation.id)
        if not submission:
            return False

        form_result = await self.db.execute(
            select(IGForm).where(IGForm.id == submission.form_id)
        )
        form = form_result.scalar_one_or_none()
        if not form:
            return False

        phase1_fields_result = await self.db.execute(
            select(IGFormField).where(
                IGFormField.form_id == form.id, IGFormField.phase == 1
            ).order_by(IGFormField.sort_order)
        )
        phase1_fields = phase1_fields_result.scalars().all()

        if submission.current_field_index >= len(phase1_fields):
            return False

        current_field = phase1_fields[submission.current_field_index]

        if submission.phase1_data is None:
            submission.phase1_data = {}
        submission.phase1_data[current_field.field_key] = message_text

        next_index = submission.current_field_index + 1
        remaining = [f for f in phase1_fields if f.sort_order > current_field.sort_order]

        if remaining:
            submission.current_field_index = next_index
            next_field = remaining[0]
            quick_replies = []
            if next_field.field_type == "phone":
                quick_replies = [{"title": "Use my phone", "payload": "USE_PHONE"}]
            elif next_field.field_type == "email":
                quick_replies = [{"title": "Use my email", "payload": "USE_EMAIL"}]

            if quick_replies:
                await client.send_quick_replies(
                    sender_id,
                    next_field.placeholder or f"Please provide your {next_field.label.lower()}:",
                    quick_replies,
                )
            else:
                await client.send_text_message(
                    sender_id,
                    next_field.placeholder or f"Please provide your {next_field.label.lower()}:",
                )
        else:
            if form.form_type == "two_phase":
                submission.status = "partial"
                link = f"{settings.FRONTEND_URL}/ig-form/{form.id}/{submission.id}"
                await client.send_button_template(
                    sender_id,
                    f"Thank you! Your details are saved. Please complete your "
                    f"{form.display_name.lower()} by selecting your options:",
                    [{"type": "web_url", "title": "Complete Booking", "url": link}],
                )
            else:
                submission.status = "completed"
                await client.send_text_message(sender_id, form.success_message)
                await self._create_lead_from_submission(submission, conversation)

        await self.db.flush()
        return True

    async def _resolve_lead_store_id(self, conversation: IGConversation) -> int:
        """The linked store if the account has one configured, otherwise
        the 'Unassigned (Instagram)' placeholder — Lead.store_id is NOT
        NULL, so without this fallback every lead captured on an account
        that hasn't been linked to a store yet would fail to save at all."""
        from ..services.common import get_or_create_unassigned_store
        account = (await self.db.execute(
            select(IGAccount).where(IGAccount.id == conversation.ig_account_id)
        )).scalar_one_or_none()
        if account and account.store_id:
            return account.store_id
        placeholder = await get_or_create_unassigned_store(self.db)
        return placeholder.id

    async def _create_lead_from_submission(
        self, submission: IGFormSubmission, conversation: IGConversation
    ):
        data = submission.phase1_data or {}
        name = data.get("name", conversation.customer_name or conversation.ig_user_id)
        phone = data.get("phone", "")

        lead = Lead(
            store_id=await self._resolve_lead_store_id(conversation),
            source="instagram",
            name=name,
            phone=phone,
            status="warm",
            stage="new",
        )
        self.db.add(lead)
        await self.db.flush()
        submission.lead_id = lead.id
        conversation.lead_id = lead.id
        await self.db.flush()

    async def _start_form(
        self, form: IGForm, conversation: IGConversation,
        client: InstagramGraphClient, sender_id: str,
        pre_filled: dict = None,
    ):
        phase1_fields_result = await self.db.execute(
            select(IGFormField).where(
                IGFormField.form_id == form.id, IGFormField.phase == 1
            ).order_by(IGFormField.sort_order)
        )
        phase1_fields = phase1_fields_result.scalars().all()
        if not phase1_fields:
            return

        submission = IGFormSubmission(
            form_id=form.id,
            conversation_id=conversation.id,
            ig_user_id=sender_id,
            phase1_data=pre_filled or {},
            status="partial",
            current_field_index=0,
        )
        self.db.add(submission)
        await self.db.flush()

        if pre_filled:
            filled_keys = set(pre_filled.keys())
            for i, field in enumerate(phase1_fields):
                if field.field_key not in filled_keys:
                    submission.current_field_index = i
                    break
            else:
                submission.status = "completed" if form.form_type == "simple" else "partial"
                if form.form_type == "two_phase":
                    link = f"{settings.FRONTEND_URL}/ig-form/{form.id}/{submission.id}"
                    await client.send_button_template(
                        sender_id,
                        f"Thank you! Your details are saved. Please complete your "
                        f"{form.display_name.lower()} by selecting your options:",
                        [{"type": "web_url", "title": "Complete Booking", "url": link}],
                    )
                else:
                    await client.send_text_message(sender_id, form.success_message)
                    await self._create_lead_from_submission(submission, conversation)
                await self.db.flush()
                return

        current_field = phase1_fields[submission.current_field_index]
        quick_replies = []
        if current_field.field_type == "phone":
            quick_replies = [{"title": "Use my phone", "payload": "USE_PHONE"}]
        elif current_field.field_type == "email":
            quick_replies = [{"title": "Use my email", "payload": "USE_EMAIL"}]

        if quick_replies:
            await client.send_quick_replies(
                sender_id,
                current_field.placeholder or f"Please provide your {current_field.label.lower()}:",
                quick_replies,
            )
        else:
            await client.send_text_message(
                sender_id,
                current_field.placeholder or f"Please provide your {current_field.label.lower()}:",
            )
        await self.db.flush()

    async def handle_dm(
        self, ig_account: IGAccount, sender_id: str,
        message_text: str, sender_name: str = "",
    ):
        settings_result = await self.db.execute(
            select(IGBotSettings).where(IGBotSettings.ig_account_id == ig_account.id)
        )
        bot_settings = settings_result.scalar_one_or_none()
        if not bot_settings or not bot_settings.dm_auto_reply_enabled:
            return

        conv_result = await self.db.execute(
            select(IGConversation).where(
                IGConversation.ig_account_id == ig_account.id,
                IGConversation.ig_user_id == sender_id,
            )
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            conversation = IGConversation(
                ig_account_id=ig_account.id,
                ig_user_id=sender_id,
                customer_name=sender_name,
            )
            self.db.add(conversation)
            await self.db.flush()

        inbound = IGMessage(
            conversation_id=conversation.id,
            direction="inbound",
            message_type="text",
            content=message_text,
        )
        self.db.add(inbound)

        token = decrypt_token(ig_account.access_token_encrypted)
        client = InstagramGraphClient(token)
        try:
            await client.set_typing_indicator(sender_id)

            active_submission = await self._get_active_submission(conversation.id)
            if active_submission:
                handled = await self._process_form_answer(
                    conversation, message_text, client, sender_id
                )
                if handled:
                    provider_info = await self.get_active_provider()
                    if provider_info:
                        provider, api_key = provider_info
                        usage_log = AIUsageLog(
                            ai_provider_id=provider.id,
                            ig_account_id=ig_account.id,
                            conversation_id=conversation.id,
                            input_tokens=0,
                            output_tokens=0,
                            model=provider.model_name,
                            cost_estimate=0,
                        )
                        self.db.add(usage_log)
                    conversation.last_message_at = inbound.created_at
                    await self.db.flush()
                    return

            provider_info = await self.get_active_provider()
            if not provider_info:
                await client.send_text_message(sender_id, bot_settings.after_hours_message)
                return

            provider, api_key = provider_info

            active_forms = await self._get_active_forms(ig_account.id)
            active_faqs = await self._get_active_faqs(ig_account.id)
            already_triggered = await self._get_triggered_forms(conversation.id)
            stock_lookup = await self._build_stock_lookup(ig_account)

            enhanced_prompt = build_system_prompt(
                base_prompt=bot_settings.ai_system_prompt,
                active_forms=active_forms,
                active_faqs=active_faqs,
                already_triggered_forms=already_triggered,
                stock_lookup_available=stock_lookup is not None,
            )

            history_result = await self.db.execute(
                select(IGMessage)
                .where(IGMessage.conversation_id == conversation.id)
                .order_by(IGMessage.created_at.desc())
                .limit(20)
            )
            history = list(reversed(history_result.scalars().all()))
            messages = [
                {
                    "role": "assistant" if m.direction == "outbound" else "user",
                    "content": m.content,
                }
                for m in history
            ]

            response = await ai_service.generate_response(
                messages=messages,
                system_prompt=enhanced_prompt,
                provider_name=provider.provider,
                api_key=api_key,
                model=provider.model_name,
                stock_lookup=stock_lookup,
            )

            if response.reply_text:
                if response.action == "trigger_form" and response.form_slug:
                    form_result = await self.db.execute(
                        select(IGForm).where(
                            IGForm.name == response.form_slug,
                            IGForm.is_active == True,
                        )
                    )
                    form = form_result.scalar_one_or_none()

                    if form and response.form_slug not in already_triggered:
                        if response.reply_text:
                            await client.send_text_message(sender_id, response.reply_text)
                            self._store_outbound(
                                conversation, response, provider,
                                ig_account, inbound,
                            )

                        await self._start_form(form, conversation, client, sender_id)
                    else:
                        await client.send_text_message(sender_id, response.reply_text)
                        self._store_outbound(
                            conversation, response, provider,
                            ig_account, inbound,
                        )
                else:
                    await client.send_text_message(sender_id, response.reply_text)
                    self._store_outbound(
                        conversation, response, provider,
                        ig_account, inbound,
                    )

                usage_log = AIUsageLog(
                    ai_provider_id=provider.id,
                    ig_account_id=ig_account.id,
                    conversation_id=conversation.id,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    model=response.model,
                    cost_estimate=ai_service.estimate_cost(
                        provider.provider, response.input_tokens, response.output_tokens
                    ),
                )
                self.db.add(usage_log)

            conversation.last_message_at = inbound.created_at
            # A complaint needs a human, not the bot continuing to reply as
            # if everything's normal — surfacing it on the conversation
            # status makes it findable/filterable from the Conversations
            # page instead of sitting silently in the message history.
            if response.action == "complaint":
                conversation.status = "needs_attention"
            await self.db.flush()

            if bot_settings.lead_qualification_enabled:
                await self._capture_passive_lead(conversation, response, message_text)
        finally:
            await client.close()

    def _store_outbound(
        self, conversation: IGConversation, response,
        provider: AIProvider, ig_account: IGAccount, inbound: IGMessage,
    ):
        outbound = IGMessage(
            conversation_id=conversation.id,
            direction="outbound",
            message_type="text",
            content=response.reply_text,
            ai_provider=provider.provider,
            ai_input_tokens=response.input_tokens,
            ai_output_tokens=response.output_tokens,
            ai_cost_estimate=ai_service.estimate_cost(
                provider.provider, response.input_tokens, response.output_tokens
            ),
        )
        self.db.add(outbound)

    async def handle_comment(
        self, ig_account: IGAccount, media_id: str, comment_id: str,
        username: str, text: str,
    ):
        settings_result = await self.db.execute(
            select(IGBotSettings).where(IGBotSettings.ig_account_id == ig_account.id)
        )
        bot_settings = settings_result.scalar_one_or_none()

        existing = await self.db.execute(
            select(IGComment).where(IGComment.comment_id == comment_id)
        )
        if existing.scalar_one_or_none():
            return

        comment_record = IGComment(
            ig_account_id=ig_account.id,
            media_id=media_id,
            comment_id=comment_id,
            username=username,
            text=text,
        )

        rules_result = await self.db.execute(
            select(IGCommentRule).where(
                IGCommentRule.ig_account_id == ig_account.id,
                IGCommentRule.is_active == True,
            ).order_by(IGCommentRule.priority.desc())
        )
        rules = rules_result.scalars().all()

        token = decrypt_token(ig_account.access_token_encrypted)
        client = InstagramGraphClient(token)

        action_taken = "none"
        ai_reply_text = None

        try:
            for rule in rules:
                matched = False
                if rule.rule_type == "keyword_match" and rule.trigger_words:
                    text_lower = text.lower()
                    matched = any(w.lower() in text_lower for w in rule.trigger_words)
                elif rule.rule_type == "ai_reply":
                    matched = True

                if not matched:
                    continue

                if rule.action == "moderation":
                    if rule.trigger_words and any(
                        w.lower() in text.lower() for w in rule.trigger_words
                    ):
                        await client.hide_comment(comment_id)
                        action_taken = "hidden"
                        break
                    continue

                if rule.action == "reply_comment" and rule.reply_template:
                    await client.reply_to_comment(comment_id, rule.reply_template)
                    action_taken = "replied_comment"
                    ai_reply_text = rule.reply_template
                    break

                if rule.action == "reply_dm":
                    provider_info = await self.get_active_provider()
                    if provider_info:
                        provider, api_key = provider_info
                        prompt = (
                            rule.ai_prompt or bot_settings.ai_system_prompt
                            if bot_settings
                            else "You are a helpful representative."
                        )
                        messages = [
                            {"role": "user", "content": f"Comment by @{username}: {text}"}
                        ]
                        response = await ai_service.generate_response(
                            messages=messages,
                            system_prompt=prompt,
                            provider_name=provider.provider,
                            api_key=api_key,
                            model=provider.model_name,
                        )
                        if response.reply_text:
                            await client.send_private_reply(comment_id, response.reply_text)
                            action_taken = "replied_dm"
                            ai_reply_text = response.reply_text

                            usage_log = AIUsageLog(
                                ai_provider_id=provider.id,
                                ig_account_id=ig_account.id,
                                input_tokens=response.input_tokens,
                                output_tokens=response.output_tokens,
                                model=response.model,
                                cost_estimate=ai_service.estimate_cost(
                                    provider.provider,
                                    response.input_tokens,
                                    response.output_tokens,
                                ),
                            )
                            self.db.add(usage_log)
                    break

                if rule.action == "reply_comment":
                    reply_text = rule.reply_template or "Thanks for your comment!"
                    await client.reply_to_comment(comment_id, reply_text)
                    action_taken = "replied_comment"
                    ai_reply_text = reply_text
                    break
        finally:
            await client.close()

        comment_record.action_taken = action_taken
        comment_record.ai_reply = ai_reply_text
        self.db.add(comment_record)
        await self.db.flush()

    async def _capture_passive_lead(
        self, conversation: IGConversation, response: AIResponse, user_message: str,
    ):
        """Creates or enriches a Lead whenever the customer has shared a
        name and/or phone number anywhere in the conversation — in a form,
        or just typed casually — instead of only reacting to a fixed list
        of sales keywords (the old _qualify_lead, which also never
        actually captured the phone number it was supposedly qualifying).
        The AI is asked to extract these on every turn (see
        ROUTE_CONVERSATION_TOOL's extracted_name/extracted_phone); a plain
        regex is only a fallback for the phone in case that extraction
        misses something obvious.
        """
        name = (response.extracted_name or "").strip()
        phone = (response.extracted_phone or "").strip()
        if not phone:
            m = _PHONE_RE.search(user_message)
            if m:
                phone = m.group(1).strip()
        if not name and not phone:
            return

        existing = None
        if conversation.lead_id:
            existing = (await self.db.execute(
                select(Lead).where(Lead.id == conversation.lead_id)
            )).scalar_one_or_none()

        if existing:
            if name and not existing.name:
                existing.name = name
            if phone and not existing.phone:
                existing.phone = phone
            await self.db.flush()
            return

        lead = Lead(
            store_id=await self._resolve_lead_store_id(conversation),
            source="instagram",
            name=name or conversation.customer_name or conversation.ig_user_id,
            phone=phone,
            status="warm",
            stage=(
                "complaint" if response.action == "complaint"
                else "callback_requested" if response.action == "callback_request"
                else "appointment_requested" if response.action == "appointment_request"
                else "new"
            ),
        )
        self.db.add(lead)
        await self.db.flush()
        conversation.lead_id = lead.id
        await self.db.flush()

    async def _build_stock_lookup(self, ig_account: IGAccount):
        """A closure the AI provider calls when the model asks to check
        real stock — only wired up when this Instagram account is linked
        to a store with a known MCP identity, otherwise the model is never
        offered the tool at all and falls back to FAQ/general answers."""
        if not ig_account.store_id:
            return None
        store = (await self.db.execute(
            select(Store).where(Store.id == ig_account.store_id)
        )).scalar_one_or_none()
        if not store or not store.mcp_country_id:
            return None

        alias_names = set((await self.db.execute(
            select(StoreMcpAlias.mcp_shop_name).where(StoreMcpAlias.store_id == store.id)
        )).scalars().all())
        if store.mcp_shop_name:
            alias_names.add(store.mcp_shop_name)
        if not alias_names:
            return None
        alias_keys = {_normalize_text(a) for a in alias_names}
        country_id = store.mcp_country_id

        async def lookup(query: str) -> str:
            from ..services.smart_service_client import smart_service
            from ..services.mcp_parsers import parse_shop_stock_position

            try:
                raw = await smart_service.shop_stock_position(country_id=country_id)
            except Exception as e:
                logger.warning("Stock lookup MCP call failed: %s", e)
                return "Stock lookup is unavailable right now — tell the customer you'll confirm shortly, do not guess a number."

            shops = parse_shop_stock_position(raw)
            my_items = []
            for s in shops:
                if _normalize_text(s.get("shop", "")) in alias_keys:
                    my_items.extend(s.get("items", []))

            if not my_items:
                return "No stock data is available for this store right now."

            query_words = [w for w in _normalize_text(query).split() if len(w) > 2]
            matches = []
            for item in my_items:
                model = item.get("model", "")
                model_norm = _normalize_text(model)
                if not query_words or any(w in model_norm for w in query_words):
                    matches.append(f"{model}: {item.get('count', 0)} in stock")

            if not matches:
                return f"No item matching '{query}' was found in this store's current stock list."
            return "; ".join(matches[:5])

        return lookup


async def poll_and_process_comments(db: AsyncSession):
    result = await db.execute(
        select(IGAccount).where(IGAccount.is_active == True)
    )
    accounts = result.scalars().all()

    for account in accounts:
        token = decrypt_token(account.access_token_encrypted)
        client = InstagramGraphClient(token)
        engine = BotEngine(db)
        try:
            media_result = await client.get_media_list(limit=10)
            if "data" not in media_result:
                continue

            for media in media_result["data"]:
                media_id = media["id"]
                comments_result = await client.get_media_comments(media_id, limit=25)
                if "data" not in comments_result:
                    continue

                for comment in comments_result["data"]:
                    await engine.handle_comment(
                        ig_account=account,
                        media_id=media_id,
                        comment_id=comment["id"],
                        username=comment.get("username", ""),
                        text=comment.get("text", ""),
                    )
        except Exception as e:
            logger.error(
                "Comment polling error for account %s: %s",
                account.ig_user_id, e,
            )
        finally:
            await client.close()
