"""The backend interface: anything that can answer a chat request, possibly using tools.

Backends emit a stream of events. The app (not the backend) owns the prompt policy, the tool registries
and the permissions: a voice request must only ever be given voice tools, never administrator tools.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCall:
    name: str
    input: dict = field(default_factory=dict)
    id: str = ""


@dataclass
class ToolResult:
    id: str
    output: str
    is_error: bool = False


@dataclass
class Done:
    usage: dict | None = None


Event = TextDelta | ToolCall | ToolResult | Done


@dataclass
class ChatRequest:
    model: str
    # User/assistant turns as sent by Home Assistant (it resends the whole history each time).
    messages: list[dict]
    # System message sent by the caller (the "Instructions" field of HA's Ollama agent), if any.
    system: str | None = None
    client: str = "unknown"


class Backend(Protocol):
    name: str

    def stream(self, request: ChatRequest) -> AsyncIterator[Event]:
        """Yield events until a final Done."""
        ...

    async def close(self) -> None: ...
