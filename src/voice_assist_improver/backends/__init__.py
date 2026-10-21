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
    # The Anthropic API backend arrives in milestone M1 (see docs/ARCHITECTURE.md).
    raise ValueError(f"unknown or not-yet-implemented backend: {settings.backend!r}")
