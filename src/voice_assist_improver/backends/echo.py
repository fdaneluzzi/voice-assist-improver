"""A development/test backend that echoes the last user message. It never calls any AI service."""
from __future__ import annotations

from collections.abc import AsyncIterator

from .base import ChatRequest, Done, Event, TextDelta


class EchoBackend:
    name = "echo"

    async def stream(self, request: ChatRequest) -> AsyncIterator[Event]:
        last = next((m["content"] for m in reversed(request.messages) if m.get("role") == "user"), "")
        reply = f"Echo: {last}"
        mid = len(reply) // 2
        yield TextDelta(reply[:mid])
        yield TextDelta(reply[mid:])
        yield Done()

    async def close(self) -> None:
        return None
