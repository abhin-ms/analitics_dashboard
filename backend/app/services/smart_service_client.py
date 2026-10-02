import json
import logging
import time
from typing import Any, Optional

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)


class SmartServiceClient:
    """Client for the BreakProtection SmartService MCP (Model Context Protocol) server.

    Communicates via JSON-RPC over SSE (Server-Sent Events) at /mcp.
    Requires OAuth 2.1 client_credentials for authentication.
    """

    def __init__(self):
        self.mcp_url = settings.SMARTSERVICE_MCP_URL
        self.token_url = settings.SMARTSERVICE_TOKEN_URL
        self.client_id = settings.SMARTSERVICE_CLIENT_ID
        self.client_secret = settings.SMARTSERVICE_CLIENT_SECRET
        self.scope = settings.SMARTSERVICE_SCOPE

        self._token: Optional[str] = None
        self._token_expiry: float = 0
        self._session_id: Optional[str] = None
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ── OAuth 2.1 Token ──────────────────────────────────────────────

    async def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 300:
            return self._token

        client = await self._get_client()
        resp = await client.post(
            self.token_url,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        logger.info("SmartService token refreshed, expires in %ds", data.get("expires_in", 3600))
        return self._token

    # ── MCP Session ──────────────────────────────────────────────────

    async def _ensure_session(self) -> str:
        if self._session_id:
            return self._session_id

        token = await self._ensure_token()
        client = await self._get_client()

        resp = await client.post(
            self.mcp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "bp-analytics-backend", "version": "1.0.0"},
                },
            },
        )
        resp.raise_for_status()

        session_id = resp.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No Mcp-Session-Id header in initialize response")

        self._session_id = session_id

        # Send initialized notification
        await client.post(
            self.mcp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
            },
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        logger.info("MCP session initialized: %s", session_id)
        return session_id

    def _reset_session(self):
        self._session_id = None

    # ── Tool Calling ─────────────────────────────────────────────────

    async def call_tool(self, name: str, args: dict[str, Any] = None, retries: int = 2) -> str:
        """Call an MCP tool and return the text content from the response.

        Args:
            name: Tool name (e.g. 'sales_summary', 'transaction_detail')
            args: Tool arguments dict
            retries: Number of retries on server-side errors

        Returns:
            The text content string from the MCP tool response.
        """
        for attempt in range(retries + 1):
            token = await self._ensure_token()
            session_id = await self._ensure_session()
            client = await self._get_client()

            payload = {
                "jsonrpc": "2.0",
                "id": int(time.time() * 1000),
                "method": "tools/call",
                "params": {"name": name, "arguments": args or {}},
            }

            resp = await client.post(
                self.mcp_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Mcp-Session-Id": session_id,
                },
                json=payload,
            )

            # Handle session errors — reset and retry. 404 is how the MCP
            # server says "unknown session" (e.g. after it restarted); without
            # this the stale session id was reused forever and every sync failed.
            if resp.status_code in (400, 401, 404) and attempt < retries:
                if resp.status_code == 401:
                    self._token = None  # token may have been revoked too
                self._reset_session()
                continue

            resp.raise_for_status()

            result = self._parse_sse_response(resp.text)

            if result and "An error occurred" not in result:
                return result

            if attempt < retries:
                self._reset_session()
                continue

        return result

    def _parse_sse_response(self, text: str) -> str:
        """Parse SSE response and extract text content from MCP result."""
        for line in text.strip().split("\n"):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if "result" in data:
                        if data["result"].get("isError"):
                            error_text = ""
                            for item in data["result"].get("content", []):
                                if item.get("type") == "text":
                                    error_text = item["text"]
                            raise RuntimeError(f"MCP tool error: {error_text}")
                        content = data["result"].get("content", [])
                        for item in content:
                            if item.get("type") == "text":
                                return item["text"]
                    if "error" in data:
                        raise RuntimeError(f"MCP error: {data['error']}")
                except json.JSONDecodeError:
                    continue
        raise RuntimeError(f"Could not parse MCP response: {text[:200]}")

    # ── Domain Methods ───────────────────────────────────────────────

    async def sales_summary(
        self,
        from_date: str,
        to_date: str = None,
        country_id: int = None,
        shop_id: int = None,
    ) -> str:
        args = {"fromDate": from_date}
        if to_date:
            args["toDate"] = to_date
        if country_id is not None:
            args["countryId"] = country_id
        if shop_id is not None:
            args["shopId"] = shop_id
        return await self.call_tool("sales_summary", args)

    async def shop_wise_sales(
        self,
        country_id: int,
        from_date: str,
        to_date: str = None,
    ) -> str:
        args = {"countryId": country_id, "fromDate": from_date}
        if to_date:
            args["toDate"] = to_date
        return await self.call_tool("shop_wise_sales", args)

    async def transaction_detail(
        self,
        from_date: str,
        to_date: str = None,
        country_id: int = None,
        shop_id: int = None,
        purchase_category_id: int = None,
        purchase_type_id: int = None,
        model_id: int = None,
        customer_search: str = None,
        limit: int = 100,
    ) -> str:
        args = {"fromDate": from_date, "limit": limit}
        if to_date:
            args["toDate"] = to_date
        if country_id is not None:
            args["countryId"] = country_id
        if shop_id is not None:
            args["shopId"] = shop_id
        if purchase_category_id is not None:
            args["purchaseCategoryId"] = purchase_category_id
        if purchase_type_id is not None:
            args["purchaseTypeId"] = purchase_type_id
        if model_id is not None:
            args["modelId"] = model_id
        if customer_search:
            args["customerSearch"] = customer_search
        return await self.call_tool("transaction_detail", args)

    async def shop_target_achievement(
        self,
        country_id: int,
        year: int,
        month: str,
        shop_id: int = None,
    ) -> str:
        args = {"countryId": country_id, "year": year, "month": month}
        if shop_id is not None:
            args["shopId"] = shop_id
        return await self.call_tool("shop_target_achievement", args)

    async def compare_country_sales(
        self,
        from_date: str,
        to_date: str = None,
        country_ids: str = None,
    ) -> str:
        args = {"fromDate": from_date}
        if to_date:
            args["toDate"] = to_date
        if country_ids:
            args["countryIds"] = country_ids
        return await self.call_tool("compare_country_sales", args)

    async def top_models(
        self,
        country_id: int,
        from_date: str,
        to_date: str = None,
        top_n: int = 10,
    ) -> str:
        args = {"countryId": country_id, "fromDate": from_date, "topN": top_n}
        if to_date:
            args["toDate"] = to_date
        return await self.call_tool("top_models", args)

    async def shop_stock_position(
        self,
        shop_id: int = None,
        country_id: int = None,
        low_stock_threshold: int = None,
    ) -> str:
        args = {}
        if shop_id is not None:
            args["shopId"] = shop_id
        if country_id is not None:
            args["countryId"] = country_id
        if low_stock_threshold is not None:
            args["lowStockThreshold"] = low_stock_threshold
        return await self.call_tool("shop_stock_position", args)

    async def pending_items_by_shop(
        self,
        country_id: int = None,
        shop_id: int = None,
        include: str = "both",
    ) -> str:
        args = {"include": include}
        if country_id is not None:
            args["countryId"] = country_id
        if shop_id is not None:
            args["shopId"] = shop_id
        return await self.call_tool("pending_items_by_shop", args)

    async def daybook_summary(
        self,
        shop_id: int,
        from_date: str,
        to_date: str = None,
    ) -> str:
        args = {"shopId": shop_id, "fromDate": from_date}
        if to_date:
            args["toDate"] = to_date
        return await self.call_tool("daybook_summary", args)

    async def cashbook_summary(self, shop_id: int) -> str:
        return await self.call_tool("cashbook_summary", {"shopId": shop_id})

    # ── Health Check ─────────────────────────────────────────────────

    async def health_check(self) -> dict:
        try:
            await self._ensure_token()
            return {"status": "ok", "message": "SmartService connection healthy"}
        except Exception as e:
            logger.error("SmartService health check failed: %s", e)
            return {"status": "error", "message": str(e)}


smart_service = SmartServiceClient()
