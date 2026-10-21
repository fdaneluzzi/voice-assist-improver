"""Stand-in backend used when the app has no API key yet: it says so out loud instead of failing."""
from __future__ import annotations

from collections.abc import AsyncIterator

from ..config import Settings
from ..i18n import t
from .base import ChatRequest, Done, Event, TextDelta


class UnconfiguredBackend:
    name = "unconfigured"

    def __init__(self, settings: Settings, reason: str):
        self.s = settings
        self.reason = reason

    async def stream(self, request: ChatRequest) -> AsyncIterator[Event]:
        yield TextDelta(t(self.s.language, "not_configured"))
        yield Done()

    async def close(self) -> None:
        return None
