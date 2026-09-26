import logging
import json
from typing import Awaitable, Callable, Optional
import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_BASE = "https://api.anthropic.com/v1"
OPENAI_BASE = "https://api.openai.com/v1"

StockLookup = Callable[[str], Awaitable[str]]


ROUTE_CONVERSATION_TOOL = {
    "name": "route_conversation",
    "description": (
        "Route the conversation to the correct action and reply to the customer. "
        "You MUST call this tool exactly once per user message — it is how your "
        "reply actually gets sent."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment": {
                "type": "string",
                "enum": ["positive", "neutral", "negative", "angry"],
                "description": "The user's sentiment in this message.",
            },
            "action": {
                "type": "string",
                "enum": [
                    "trigger_form", "answer_faq", "general_reply",
                    "complaint", "callback_request", "appointment_request",
                ],
                "description": (
                    "Which outcome this message represents:\n"
                    "- trigger_form: the user clearly needs a structured data-collection flow.\n"
                    "- answer_faq: the question matches a provided FAQ entry.\n"
                    "- complaint: the user is unhappy about something that already happened "
                    "(a delayed claim, a bad experience, a broken product) — not a sales question.\n"
                    "- callback_request: the user wants a human to call them, with no form involved.\n"
                    "- appointment_request: the user wants to visit or book a specific time at the store.\n"
                    "- general_reply: anything else, including normal sales conversation."
                ),
            },
            "form_slug": {
                "type": "string",
                "description": (
                    "The slug of the form to trigger. Required when action is "
                    "'trigger_form'. Must be one of the slugs listed in the system "
                    "prompt. Leave empty or omit for other actions."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Self-reported confidence 0.0-1.0 for the chosen action.",
            },
            "reply_text": {
                "type": "string",
                "description": (
                    "The natural-language reply to send to the user. When action is "
                    "'trigger_form', this is a brief acknowledgment before the form "
                    "starts. When action is 'answer_faq', answer ONLY from the "
                    "injected FAQ context — never invent details. For 'complaint', "
                    "acknowledge and reassure a human will follow up — do not try to sell. "
                    "For 'callback_request' or 'appointment_request', confirm you've noted "
                    "it once you have a number and a time/preference."
                ),
            },
            "extracted_name": {
                "type": "string",
                "description": (
                    "Fill this in ANY time the customer states their own name anywhere in "
                    "the conversation, in ANY message, regardless of what action you chose "
                    "for this turn — even in a casual sentence like 'I'm Priya btw'. Leave "
                    "empty if no name has been shared."
                ),
            },
            "extracted_phone": {
                "type": "string",
                "description": (
                    "Fill this in ANY time the customer shares a phone number anywhere in "
                    "the conversation, in ANY message, regardless of what action you chose "
                    "for this turn — even in a casual sentence, not just inside a form. "
                    "Leave empty if no phone number has been shared."
                ),
            },
        },
        "required": ["sentiment", "action", "confidence", "reply_text"],
    },
}

CHECK_STOCK_TOOL = {
    "name": "check_stock",
    "description": (
        "Look up REAL, current stock for a specific product/item at this store from "
        "the live inventory system. Call this whenever a customer asks if something "
        "is in stock, available, or how many are left. Never guess or invent a stock "
        "number — always call this tool instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The product/item the customer is asking about, e.g. "
                    "'iPhone 15 tempered glass' or 'Samsung S24 screen guard'."
                ),
            },
        },
        "required": ["query"],
    },
}


class AIResponse:
    def __init__(
        self,
        text: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
        action: str = "general_reply",
        form_slug: str = "",
        sentiment: str = "neutral",
        confidence: float = 0.0,
        reply_text: str = "",
        extracted_name: str = "",
        extracted_phone: str = "",
    ):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        self.action = action
        self.form_slug = form_slug
        self.sentiment = sentiment
        self.confidence = confidence
        self.reply_text = reply_text
        self.extracted_name = extracted_name
        self.extracted_phone = extracted_phone


# The non-negotiable "how to behave" layer, appended after the business's own
# base prompt (their domain instructions) plus forms/FAQ context below. Kept
# separate from the editable base prompt so every account gets these rules
# immediately, without needing its own prompt hand-edited.
BEHAVIOR_RULES = """
How to behave (applies no matter what the base instructions above say):

SOUND HUMAN, NOT LIKE A BOT.
- Never say you're an AI, a bot, or an assistant. Never apologize for being automated.
- Vary your phrasing — don't reuse the same opener or sentence structure every reply.
- Default to SHORT — 1-2 sentences, the way a real staff member would text back, not a
  formal paragraph. Only go longer when the situation genuinely needs it: explaining a
  claim/complaint process step by step, listing multiple real options, or walking
  through a form. Never pad a simple answer with extra sentences just to sound thorough.
- Match the customer's energy and language (casual stays casual, Hindi/Malayalam/etc.
  stays in that language if they wrote in it).

SELL LIKE A PERSON WHO WANTS THE CUSTOMER TO COME BACK, NOT A PRICE-QUOTE MACHINE.
- If someone only asks the price, answer honestly — but never stop there. Give one
  genuine reason to keep the conversation going: ask what device/model they have, offer
  a relevant detail (what it covers, how fast it can be set up), or ask a natural
  follow-up. A reply that is JUST a price with nothing else is a wasted opportunity —
  that customer will not come back.
- Never be pushy or fake-urgent ("only today!", "hurry!"). Genuine curiosity and
  helpfulness converts better than pressure.

HANDLE THESE SITUATIONS DIFFERENTLY, NOT WITH THE SAME SALES TONE:
- Complaint (something already went wrong): drop the sales tone entirely. Acknowledge
  the frustration is valid, say a real person will follow up, and ask for whatever
  contact detail is needed to do that. Do not try to sell anything in this reply.
- Callback or appointment request: don't push a form if one isn't needed — just ask
  for the missing piece (a number, a preferred time) conversationally.

CAPTURE CONTACT INFO WHENEVER IT APPEARS, NOT JUST INSIDE A FORM.
- If the customer states their name or phone number in ANY message, in ANY normal
  sentence, put it in extracted_name / extracted_phone on that same turn — even if the
  rest of the message is about something else entirely and even if you're not
  currently running a form.

USE check_stock FOR REAL AVAILABILITY, NEVER GUESS.
- If a stock/availability tool is available to you and the customer asks whether
  something is in stock or how many are left, call it and answer with the real number.
  If no stock tool is available, or the customer is asking about pricing/plans rather
  than physical stock, answer from the FAQ context instead — never invent a stock count.
"""


def build_system_prompt(
    base_prompt: str,
    active_forms: list[dict],
    active_faqs: list[dict],
    already_triggered_forms: list[str] | None = None,
    stock_lookup_available: bool = False,
) -> str:
    sections = [base_prompt, BEHAVIOR_RULES]

    if active_forms:
        form_list = "\n".join(
            f"- slug=\"{f['slug']}\": {f['description']} "
            f"(collects: {', '.join(f['field_keys'])})"
            for f in active_forms
        )
        sections.append(
            f"\nAvailable forms (use the form_slug value exactly):\n{form_list}\n"
            f"\nRules for forms:\n"
            f"- Only trigger a form when the user clearly needs that data collected.\n"
            f"- Do NOT re-trigger a form the user has already completed or is in the "
            f"middle of — if the form slug appears in 'already_triggered_forms', do "
            f"not use action='trigger_form' for it unless the user explicitly asks to "
            f"start over.\n"
            f"- Set reply_text to a brief, warm acknowledgment before the form begins."
        )

    if active_faqs:
        faq_block = "\n\n".join(
            f"Q: {faq['question']}\nA: {faq['answer']}"
            for faq in active_faqs
        )
        sections.append(
            f"\nFAQ knowledge base — answer ONLY from these entries when action is "
            f"'answer_faq'. If no FAQ matches, use 'general_reply' and let a human "
            f"follow up.\n\n{faq_block}"
        )

    if already_triggered_forms:
        sections.append(
            f"\nForms already triggered in this conversation: "
            f"{', '.join(already_triggered_forms)}. Do not re-trigger these unless "
            f"the user explicitly requests it."
        )

    if stock_lookup_available:
        sections.append(
            "\nA check_stock tool is available for this store's real, live inventory — "
            "use it whenever the customer asks about availability or quantity."
        )

    sections.append(
        "\nYou MUST call the route_conversation tool exactly once as your final action "
        "each turn. Do not output any text outside tool calls."
    )

    return "\n".join(sections)


def _extract_tool_use(content_blocks: list[dict], name: str) -> Optional[dict]:
    for block in content_blocks:
        if block.get("type") == "tool_use" and block.get("name") == name:
            return block
    return None


def _route_result_to_response(tool_input: dict, input_tokens: int, output_tokens: int, model: str) -> AIResponse:
    return AIResponse(
        text=tool_input.get("reply_text", ""),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        action=tool_input.get("action", "general_reply"),
        form_slug=tool_input.get("form_slug", ""),
        sentiment=tool_input.get("sentiment", "neutral"),
        confidence=tool_input.get("confidence", 0.0),
        reply_text=tool_input.get("reply_text", ""),
        extracted_name=tool_input.get("extracted_name", ""),
        extracted_phone=tool_input.get("extracted_phone", ""),
    )


class ClaudeProvider:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=60.0)

    async def _call(self, messages: list[dict], system_prompt: str, tools: list[dict], tool_choice: dict, max_tokens: int):
        resp = await self.client.post(
            f"{ANTHROPIC_BASE}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str,
        max_tokens: int = 1024,
        stock_lookup: Optional[StockLookup] = None,
    ) -> AIResponse:
        formatted_messages = [
            {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            for msg in messages
        ]
        total_in = total_out = 0
        try:
            if stock_lookup is not None:
                # Two-step: let the model optionally check real stock first,
                # then force it to produce the final structured reply — a
                # single forced tool call can never pause to look something
                # up, so a genuine stock question would otherwise always be
                # answered with a guess.
                data = await self._call(
                    formatted_messages, system_prompt,
                    tools=[ROUTE_CONVERSATION_TOOL, CHECK_STOCK_TOOL],
                    tool_choice={"type": "auto"}, max_tokens=max_tokens,
                )
                usage = data.get("usage", {})
                total_in += usage.get("input_tokens", 0)
                total_out += usage.get("output_tokens", 0)
                content = data.get("content", [])

                stock_call = _extract_tool_use(content, "check_stock")
                if stock_call:
                    query = stock_call.get("input", {}).get("query", "")
                    try:
                        result_text = await stock_lookup(query)
                    except Exception as e:
                        logger.warning("Stock lookup failed: %s", e)
                        result_text = "Stock lookup is unavailable right now."

                    formatted_messages = formatted_messages + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": [
                            {"type": "tool_result", "tool_use_id": stock_call.get("id"), "content": result_text}
                        ]},
                    ]
                    data = await self._call(
                        formatted_messages, system_prompt,
                        tools=[ROUTE_CONVERSATION_TOOL],
                        tool_choice={"type": "tool", "name": "route_conversation"},
                        max_tokens=max_tokens,
                    )
                    usage = data.get("usage", {})
                    total_in += usage.get("input_tokens", 0)
                    total_out += usage.get("output_tokens", 0)
                    content = data.get("content", [])

                route_call = _extract_tool_use(content, "route_conversation")
                if route_call:
                    return _route_result_to_response(route_call.get("input", {}), total_in, total_out, self.model)

                fallback_text = next((b.get("text", "") for b in content if b.get("type") == "text"), "")
                return AIResponse(text=fallback_text, input_tokens=total_in, output_tokens=total_out, model=self.model)

            data = await self._call(
                formatted_messages, system_prompt,
                tools=[ROUTE_CONVERSATION_TOOL],
                tool_choice={"type": "tool", "name": "route_conversation"},
                max_tokens=max_tokens,
            )
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            content = data.get("content", [])
            route_call = _extract_tool_use(content, "route_conversation")
            if route_call:
                return _route_result_to_response(route_call.get("input", {}), input_tokens, output_tokens, self.model)

            fallback_text = next((b.get("text", "") for b in content if b.get("type") == "text"), "")
            return AIResponse(
                text=fallback_text, input_tokens=input_tokens, output_tokens=output_tokens, model=self.model,
            )
        except Exception as e:
            logger.error("Claude API error: %s", e)
            return AIResponse(
                text="", input_tokens=total_in, output_tokens=total_out, model=self.model
            )

    async def close(self):
        await self.client.aclose()


class OpenAIProvider:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=60.0)

    @staticmethod
    def _as_openai_tool(tool: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }

    async def _call(self, messages: list[dict], tools: list[dict], tool_choice, max_tokens: int):
        resp = await self.client.post(
            f"{OPENAI_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str,
        max_tokens: int = 1024,
        stock_lookup: Optional[StockLookup] = None,
    ) -> AIResponse:
        formatted_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            formatted_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

        route_tool = self._as_openai_tool(ROUTE_CONVERSATION_TOOL)
        total_in = total_out = 0
        try:
            if stock_lookup is not None:
                stock_tool = self._as_openai_tool(CHECK_STOCK_TOOL)
                data = await self._call(
                    formatted_messages, tools=[route_tool, stock_tool],
                    tool_choice="auto", max_tokens=max_tokens,
                )
                usage = data.get("usage", {})
                total_in += usage.get("prompt_tokens", 0)
                total_out += usage.get("completion_tokens", 0)
                message = (data.get("choices") or [{}])[0].get("message", {})
                tool_calls = message.get("tool_calls", []) or []
                stock_call = next((c for c in tool_calls if c.get("function", {}).get("name") == "check_stock"), None)

                if stock_call:
                    try:
                        args = json.loads(stock_call.get("function", {}).get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result_text = await stock_lookup(args.get("query", ""))
                    except Exception as e:
                        logger.warning("Stock lookup failed: %s", e)
                        result_text = "Stock lookup is unavailable right now."

                    formatted_messages = formatted_messages + [
                        message,
                        {"role": "tool", "tool_call_id": stock_call.get("id"), "content": result_text},
                    ]
                    data = await self._call(
                        formatted_messages, tools=[route_tool],
                        tool_choice={"type": "function", "function": {"name": "route_conversation"}},
                        max_tokens=max_tokens,
                    )
                    usage = data.get("usage", {})
                    total_in += usage.get("prompt_tokens", 0)
                    total_out += usage.get("completion_tokens", 0)
                    message = (data.get("choices") or [{}])[0].get("message", {})
                    tool_calls = message.get("tool_calls", []) or []

                route_call = next((c for c in tool_calls if c.get("function", {}).get("name") == "route_conversation"), None)
                if route_call:
                    try:
                        tool_result = json.loads(route_call.get("function", {}).get("arguments", "{}"))
                    except json.JSONDecodeError:
                        tool_result = {}
                    return _route_result_to_response(tool_result, total_in, total_out, self.model)

                return AIResponse(
                    text=message.get("content", "") or "", input_tokens=total_in, output_tokens=total_out, model=self.model,
                )

            data = await self._call(
                formatted_messages, tools=[route_tool],
                tool_choice={"type": "function", "function": {"name": "route_conversation"}},
                max_tokens=max_tokens,
            )
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                tool_calls = message.get("tool_calls", [])
                if tool_calls:
                    try:
                        tool_result = json.loads(tool_calls[0].get("function", {}).get("arguments", "{}"))
                    except json.JSONDecodeError:
                        tool_result = {}
                    return _route_result_to_response(tool_result, input_tokens, output_tokens, self.model)
                return AIResponse(
                    text=message.get("content", ""), input_tokens=input_tokens, output_tokens=output_tokens, model=self.model,
                )
            return AIResponse(text="", input_tokens=input_tokens, output_tokens=output_tokens, model=self.model)
        except Exception as e:
            logger.error("OpenAI API error: %s", e)
            return AIResponse(text="", input_tokens=total_in, output_tokens=total_out, model=self.model)

    async def close(self):
        await self.client.aclose()


class AIService:
    def __init__(self):
        self._providers: dict[str, object] = {}

    def _get_provider(self, provider_name: str, api_key: str, model: str):
        if provider_name == "claude":
            return ClaudeProvider(api_key=api_key, model=model or "claude-sonnet-4-6")
        elif provider_name == "openai":
            return OpenAIProvider(api_key=api_key, model=model or "gpt-4o")
        raise ValueError(f"Unknown provider: {provider_name}")

    async def generate_response(
        self,
        messages: list[dict],
        system_prompt: str,
        provider_name: str,
        api_key: str,
        model: str = "",
        stock_lookup: Optional[StockLookup] = None,
    ) -> AIResponse:
        provider = self._get_provider(provider_name, api_key, model)
        try:
            return await provider.generate(messages, system_prompt, stock_lookup=stock_lookup)
        finally:
            await provider.close()

    def estimate_cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        rates = {
            "claude": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
            "openai": {"input": 2.5 / 1_000_000, "output": 10.0 / 1_000_000},
        }
        r = rates.get(provider, rates["openai"])
        return input_tokens * r["input"] + output_tokens * r["output"]


ai_service = AIService()
