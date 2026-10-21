"""The web UI (shown inside Home Assistant through ingress) and its JSON API, all under /ui.

Everything here is read-only except the suggestion actions. The UI is served relative to its own URL so it
works behind the ingress path prefix that Home Assistant adds.
"""
from __future__ import annotations

import asyncio
import logging
from importlib import resources
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .analysis import Analyzer
from .config import Settings
from .ha.aliases import AliasError, apply_alias, remove_alias
from .ha.entities import fetch_entities
from .ha.ws import HAError
from .models import ModelCatalog
from .store import STATUSES, Store

log = logging.getLogger(__name__)

RECENT = 30


class StatusBody(BaseModel):
    status: str


def _public_suggestion(s: dict) -> dict:
    return {k: s[k] for k in ("id", "kind", "entity_id", "alias", "phrase", "title", "detail", "evidence",
                              "status", "verified", "updated")}


def build_router(settings: Settings, store: Store, backend: Any, analyzer: Analyzer | None,
                 catalog: ModelCatalog | None = None) -> APIRouter:
    router = APIRouter(prefix="/ui")
    tasks: set[asyncio.Task] = set()  # keep references so background runs are not garbage collected

    @router.get("/", response_class=HTMLResponse)
    async def page():
        return resources.files("voice_assist_improver.web").joinpath("index.html").read_text("utf-8")

    @router.get("/api/summary")
    async def summary():
        tz = settings.timezone
        configured = getattr(backend, "name", "") != "unconfigured"
        last = store.last_analysis_run()
        models = await catalog.list() if catalog else []
        missing = await catalog.missing(settings.model, settings.analysis_model) if catalog else []
        return {
            "status": {
                "configured": configured, "reason": getattr(backend, "reason", ""),
                "backend": getattr(backend, "name", ""), "model": settings.model,
                "analysis_model": settings.analysis_model, "language": settings.language,
                "month_cost": store.month_cost(tz), "budget": settings.monthly_budget_usd,
                "web_search": settings.web_search, "analysis_hour": settings.analysis_hour,
                "analysis_days": settings.analysis_days,
                "models": [m["id"] for m in models], "missing_models": missing,
            },
            "today": store.day_totals(tz),
            "daily": store.fallbacks_per_day(days=14, timezone=tz),
            "top_phrases": store.top_phrases(days=14, limit=10),
            "recent": [
                {"id": r["id"], "ts": r["ts"], "utterance": r["utterance"], "reply": r["reply"],
                 "tools": [t["name"] for t in r["tools"]], "latency_ms": r["latency_ms"],
                 "cost_usd": r["cost_usd"], "error": r["error"], "model": r["model"]}
                for r in store.recent_interactions(RECENT)],
            "analysis": {"running": bool(analyzer and analyzer.running), "available": analyzer is not None,
                         "last": last},
        }

    @router.delete("/api/interactions/{interaction_id}")
    async def delete_interaction(interaction_id: int):
        if not store.delete_interaction(interaction_id):
            raise HTTPException(404, "no such request")
        return {"ok": True}

    @router.get("/api/suggestions")
    async def suggestions(status: str | None = None):
        if status is not None and status not in STATUSES:
            raise HTTPException(400, "unknown status")
        return {"suggestions": [_public_suggestion(s) for s in store.list_suggestions(status)]}

    @router.post("/api/suggestions/{suggestion_id}/status")
    async def set_status(suggestion_id: int, body: StatusBody):
        if body.status not in STATUSES:
            raise HTTPException(400, "unknown status")
        if not store.set_suggestion_status(suggestion_id, body.status):
            raise HTTPException(404, "no such suggestion")
        return {"ok": True}

    def alias_suggestion(suggestion_id: int) -> dict:
        s = store.get_suggestion(suggestion_id)
        if s is None:
            raise HTTPException(404, "no such suggestion")
        if s["kind"] != "alias" or not s["entity_id"] or not s["alias"]:
            raise HTTPException(400, "this suggestion cannot be applied automatically")
        return s

    @router.post("/api/suggestions/{suggestion_id}/apply")
    async def apply(suggestion_id: int):
        """Executes the (already validated) alias plan; the executor re-checks everything and verifies it."""
        s = alias_suggestion(suggestion_id)
        try:
            message = await apply_alias(settings, s["entity_id"], s["alias"])
        except (AliasError, HAError) as exc:
            raise HTTPException(409, str(exc)) from exc
        store.set_suggestion_status(suggestion_id, "done", verified=True)
        return {"ok": True, "message": message}

    @router.post("/api/suggestions/{suggestion_id}/undo")
    async def undo(suggestion_id: int):
        s = alias_suggestion(suggestion_id)
        try:
            message = await remove_alias(settings, s["entity_id"], s["alias"])
        except (AliasError, HAError) as exc:
            raise HTTPException(409, str(exc)) from exc
        store.set_suggestion_status(suggestion_id, "new")
        return {"ok": True, "message": message}

    @router.post("/api/suggestions/{suggestion_id}/verify")
    async def verify(suggestion_id: int):
        """For a suggestion the user applied by hand: check in Home Assistant that the alias exists."""
        s = alias_suggestion(suggestion_id)
        try:
            entities = await fetch_entities(settings)
        except HAError as exc:
            raise HTTPException(502, str(exc)) from exc
        target = next((e for e in entities if e["id"] == s["entity_id"]), None)
        found = bool(target and s["alias"] in target["aliases"])
        store.set_suggestion_status(suggestion_id, "done" if found else s["status"], verified=found)
        return {"ok": True, "verified": found}

    @router.post("/api/analyze")
    async def analyze():
        if analyzer is None:
            raise HTTPException(409, "analysis needs the Anthropic backend")
        if analyzer.running:
            return {"started": False, "running": True}
        task = asyncio.create_task(analyzer.run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"started": True}

    return router
