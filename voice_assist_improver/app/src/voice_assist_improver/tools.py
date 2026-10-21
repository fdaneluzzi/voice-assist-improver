"""Tool registries. The app, not the prompt, decides which tools a request can use.

The voice registry exposes Home Assistant's Assist tools (read and control the entities that were exposed to
Assist). Administrator tools will live in a separate registry that is only handed to the scheduled analysis
and to "do it for me", never to a voice request.
"""
from __future__ import annotations

import fnmatch
import logging
import time
from typing import Protocol

from .ha.mcp import MCPClient, MCPError

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 60_000


class ToolSource(Protocol):
    async def list_tools(self) -> list[dict]: ...
    async def call_tool(self, name: str, arguments: dict | None = None) -> tuple[str, bool]: ...


class VoiceToolRegistry:
    def __init__(
        self, source: ToolSource | MCPClient, denylist: tuple[str, ...] = (), cache_seconds: int = 300
    ):
        self.source = source
        self.denylist = denylist
        self.cache_seconds = cache_seconds
        self._tools: dict[str, dict] = {}
        self._loaded_at = 0.0

    def _allowed(self, name: str) -> bool:
        return not any(fnmatch.fnmatch(name, pattern) for pattern in self.denylist)

    async def refresh(self, force: bool = False) -> None:
        """Load the tool list (cached). Keeps the previous list if Home Assistant cannot be reached."""
        if not force and self._tools and time.monotonic() - self._loaded_at < self.cache_seconds:
            return
        try:
            tools = await self.source.list_tools()
        except Exception as exc:
            if not self._tools:
                raise
            log.warning("could not refresh the Home Assistant tool list, using the cached one: %s", exc)
            return
        self._tools = {t["name"]: t for t in tools if self._allowed(t["name"])}
        self._loaded_at = time.monotonic()

    def api_tools(self) -> list[dict]:
        """Tool definitions in the Anthropic format, in a deterministic order (stable prompt cache)."""
        return [
            {"name": name, "description": tool.get("description", ""),
             "input_schema": tool.get("inputSchema") or {"type": "object", "properties": {}}}
            for name, tool in sorted(self._tools.items())
        ]

    async def execute(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Run a tool the model asked for. Returns (text, is_error); never raises."""
        if name not in self._tools:
            return f"Unknown tool: {name}", True
        try:
            text, is_error = await self.source.call_tool(name, arguments)
        except MCPError as exc:
            return f"Tool failed: {exc}", True
        except Exception as exc:  # network errors and the like must not crash the conversation
            log.warning("tool %s failed: %s", name, exc)
            return f"Tool failed: {type(exc).__name__}", True
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n[truncated]"
        return text, is_error
