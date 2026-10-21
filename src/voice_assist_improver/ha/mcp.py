"""A minimal client for Home Assistant's MCP server (streamable HTTP, JSON-RPC).

Home Assistant serves its Assist tools (control and read the entities exposed to Assist) over MCP at
`<ha_url>/api/mcp`. This client does only what we need: initialize, list tools, call a tool.
"""
from __future__ import annotations

import json
from itertools import count
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-03-26"


class MCPError(Exception):
    pass


def _parse_body(response: httpx.Response) -> dict[str, Any]:
    """The server answers with plain JSON, or with an SSE stream whose `data:` line carries the JSON."""
    ctype = response.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise MCPError("empty event stream from the MCP server")
    return response.json()


class MCPClient:
    def __init__(
        self, url: str, token: str, *, client: httpx.AsyncClient | None = None, timeout: float = 30.0
    ):
        self.url = url
        self._token = token
        self._http = client or httpx.AsyncClient(timeout=timeout)
        self._owns_http = client is None
        self._ids = count(1)
        self._session_id: str | None = None
        self._initialized = False

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _rpc(self, method: str, params: dict | None = None) -> Any:
        body = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}}
        response = await self._http.post(self.url, json=body, headers=self._headers())
        if response.status_code in (401, 403):
            raise MCPError(f"Home Assistant rejected the MCP token (HTTP {response.status_code})")
        response.raise_for_status()
        if sid := response.headers.get("mcp-session-id"):
            self._session_id = sid
        message = _parse_body(response)
        if "error" in message:
            raise MCPError(str(message["error"].get("message", message["error"])))
        return message.get("result")

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                       "clientInfo": {"name": "voice-assist-improver", "version": "0.0.1"}})
        self._initialized = True

    async def list_tools(self) -> list[dict]:
        await self.initialize()
        result = await self._rpc("tools/list")
        return list(result.get("tools", []))

    async def call_tool(self, name: str, arguments: dict | None = None) -> tuple[str, bool]:
        """Run a tool. Returns (text, is_error)."""
        await self.initialize()
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        parts = [p.get("text", "") for p in result.get("content", []) if p.get("type") == "text"]
        text = "\n".join(parts)
        return text, bool(result.get("isError"))
