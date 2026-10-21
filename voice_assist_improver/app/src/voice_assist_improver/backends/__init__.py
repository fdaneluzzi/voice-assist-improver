from __future__ import annotations

from ..config import Settings
from .base import Backend, ChatRequest, Done, Event, TextDelta, ToolCall, ToolResult
from .echo import EchoBackend

__all__ = [
    "Backend", "ChatRequest", "Done", "EchoBackend", "Event", "TextDelta", "ToolCall", "ToolResult",
    "create_backend",
]


def create_backend(settings: Settings) -> Backend:
    if settings.backend == "echo":
        return EchoBackend()
    if settings.backend == "anthropic":
        # Imported here so the echo backend works without the SDK being importable.
        from anthropic import AsyncAnthropic

        from ..ha.mcp import MCPClient
        from ..tools import VoiceToolRegistry
        from .anthropic_api import AnthropicBackend

        if not settings.anthropic_api_key:
            raise ValueError("VAI_ANTHROPIC_API_KEY is not set")
        token = settings.ha_mcp_token or settings.ha_token
        if not token:
            raise ValueError("VAI_HA_MCP_TOKEN (or VAI_HA_TOKEN) is not set")
        mcp = MCPClient(settings.ha_mcp_url, token)
        registry = VoiceToolRegistry(mcp, settings.voice_tool_denylist, settings.tool_cache_seconds)
        workspace = settings.anthropic_workspace_id
        headers = {"anthropic-workspace-id": workspace} if workspace else None
        client = AsyncAnthropic(api_key=settings.anthropic_api_key, default_headers=headers)
        return AnthropicBackend(settings, registry, client, extra_close=(mcp.close,))
    raise ValueError(f"unknown backend: {settings.backend!r}")
