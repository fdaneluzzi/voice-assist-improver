"""The models the API key can actually use, from the provider's models endpoint.

Model names change over time, so nothing here is a hard-coded list: the choice of model is a plain setting,
and this catalog tells the user (and Home Assistant's model picker) what exists right now.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class ModelCatalog:
    def __init__(self, client: Any, ttl: float = 3600.0):
        self.client = client
        self.ttl = ttl
        self._models: list[dict] = []
        self._fetched = 0.0

    async def list(self) -> list[dict]:
        """[{"id", "name"}], newest first as the API returns them. Cached; on failure, the last good list."""
        if self._models and time.monotonic() - self._fetched < self.ttl:
            return self._models
        try:
            page = await self.client.models.list(limit=100)
            self._models = [{"id": m.id, "name": getattr(m, "display_name", "") or m.id} for m in page.data]
            self._fetched = time.monotonic()
        except Exception as exc:  # the catalog is informational: never break the app over it
            log.warning("could not list models: %s", type(exc).__name__)
            self._fetched = time.monotonic() - self.ttl + 60  # retry in a minute, not on every request
        return self._models

    async def missing(self, *wanted: str) -> list[str]:
        """The wanted model ids that the catalog knows are NOT available. Empty if the list is unknown."""
        known = {m["id"] for m in await self.list()}
        return [w for w in wanted if known and w not in known]
