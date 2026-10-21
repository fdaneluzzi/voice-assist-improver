"""The learning loop: read the phrases that reached the LLM and propose improvements to Home Assistant.

The model only *proposes*. Everything it returns is validated here by deterministic code (the entity is
exposed to Assist and safe to alias, the alias is not ambiguous, the phrase was really said) before it is
stored, and nothing touches Home Assistant until the user applies it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .budget import Budget
from .config import Settings
from .cost import Usage, usage_record
from .ha.aliases import AliasError, check_alias
from .ha.automations import PlanError, build_plan, describe_services, plan_fingerprint_text
from .ha.entities import fetch_entities
from .store import Store
from .text import norm

log = logging.getLogger(__name__)

MAX_PHRASES = 40
MAX_SUGGESTIONS = 15
MAX_TIPS = 3
MAX_TOOL_INPUT_CHARS = 160

REPORT_TOOL = {
    "name": "report_suggestions",
    "description": "Report the improvements found. Call it exactly once; use an empty list if none.",
    "input_schema": {
        "type": "object",
        "properties": {"suggestions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["alias", "automation", "scene", "tip"]},
                "phrase": {"type": "string", "description": "The phrase from the list behind this."},
                "title": {"type": "string", "description": "One short line for the user."},
                "detail": {"type": "string", "description": "One or two sentences of explanation."},
                "entity_id": {"type": "string", "description": "alias only: the entity that should answer."},
                "alias": {"type": "string", "description": "alias only: the name the user actually said."},
                "sentences": {"type": "array", "items": {"type": "string"},
                              "description": "automation/scene: up to 3 extra ways to say it (plain words)."},
                "actions": {"type": "array", "description": "automation only: what to do.", "items": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "domain.service, e.g. light.turn_on"},
                        "entity_ids": {"type": "array", "items": {"type": "string"}},
                        "data": {"type": "object", "description": "service data, e.g. {brightness_pct: 30}"},
                    },
                    "required": ["service", "entity_ids"]}},
                "name": {"type": "string", "description": "scene only: the scene name."},
                "states": {"type": "array", "description": "scene only: the state of each entity.", "items": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "state": {"type": "string", "description": "on, off, open, closed or an HVAC mode"},
                        "data": {"type": "object", "description": "e.g. {brightness_pct: 30}"},
                    },
                    "required": ["entity_id", "state"]}},
                "response": {"type": "string", "description": "automation/scene: short plain spoken reply."},
            },
            "required": ["kind", "phrase", "title"],
        }}},
        "required": ["suggestions"],
    },
}

SYSTEM_PROMPT = """You help improve a smart home voice assistant (Home Assistant "Assist").

Assist understands a command locally, for free and instantly, only when it matches the exact name of an \
entity, an alias, the area name, or a sentence-triggered automation. Everything else falls back to a slow, \
paid LLM. You get the phrases that fell back recently, what the LLM did about them, and the entities \
exposed to Assist with their names and aliases. Find changes that let Assist handle those phrases locally.

Kinds, from simplest to most involved. Prefer the simplest that fixes the phrase:
- "alias": the phrase refers to ONE entity by a name Assist does not know. Propose that name as an \
alias for that entity. The alias must be the noun phrase the user said (for example "pendente da sala"), \
without verbs or filler words, and must literally appear in the phrase. Use only entity ids listed.
- "automation": a command that does a fixed thing the LLM did the same way each time (set brightness, \
turn several lights on and off, set a temperature). Give "actions" as a list of {service, entity_ids, \
data}. Allowed services and data: {services}. The user's own phrase becomes the trigger sentence \
automatically; "sentences" may add up to 3 variants. "response" is an optional short reply.
- "scene": a named mood or mode that sets several entities to given states ("modo cinema"). Give "name" and \
"states" (light on/off with brightness_pct and color_temp_kelvin; switch on/off; fan on/off with percentage; \
cover open/closed with position; climate hvac mode with temperature).
- "tip": something none of the above can fix but the user could act on. At most three.
- Never use entities that are not in the list. Never invent services, attributes or templates.
- Do not invent anything from words that look like speech-recognition mistakes unless the phrase repeats.
- Phrases that genuinely need an LLM (weather, general questions, open conversation) need no suggestion.
- Prefer phrases that repeat. Quality over quantity: an empty list is a good answer.
- Write titles and details in the language the user asks for."""


def system_prompt() -> str:
    return SYSTEM_PROMPT.replace("{services}", describe_services())


def fingerprint(kind: str, entity_id: str | None, text: str) -> str:
    """Stable identity of a suggestion, from structured fields only, so de-duplication and the 'never again'
    list do not depend on the model's wording."""
    return hashlib.sha1(f"{kind}|{entity_id or ''}|{norm(text)}".encode()).hexdigest()[:16]


def summarize_phrases(interactions: list[dict]) -> list[dict]:
    """Group successful interactions by phrase: count, latest reply, and the tools the LLM used."""
    groups: dict[str, dict] = {}
    for r in interactions:
        if r["error"] or not r["utterance"].strip():
            continue
        g = groups.setdefault(norm(r["utterance"]), {
            "phrase": r["utterance"].strip(), "count": 0, "reply": "", "tools": [], "last": 0.0})
        g["count"] += 1
        if r["ts"] >= g["last"]:
            g["last"], g["phrase"], g["reply"] = r["ts"], r["utterance"].strip(), r["reply"] or ""
            g["tools"] = [
                f"{t['name']}{json.dumps(t.get('input') or {}, ensure_ascii=False)[:MAX_TOOL_INPUT_CHARS]}"
                for t in r["tools"]]
    return sorted(groups.values(), key=lambda g: (-g["count"], -g["last"]))[:MAX_PHRASES]


def build_prompt(phrases: list[dict], entities: list[dict], language: str) -> str:
    lines = ["## Phrases that reached the LLM"]
    for g in phrases:
        tools = "; ".join(g["tools"]) or "no tools"
        lines.append(f'- "{g["phrase"]}" x{g["count"]} | LLM did: {tools} | replied: {g["reply"][:120]!r}')
    lines.append("\n## Entities exposed to Assist (id | name | area | aliases)")
    for e in entities:
        lines.append(f"{e['id']} | {e['name']} | {e['area'] or '-'} | {', '.join(e['aliases']) or '-'}")
    lines.append(f"\nWrite titles and details in: {language}.")
    return "\n".join(lines)


def validate(items: list[dict], phrases: list[dict], entities: list[dict]) -> tuple[list[dict], list[str]]:
    """Keep the proposals that pass the deterministic checks. Returns (accepted, reasons for rejections)."""
    seen = {norm(g["phrase"]): g for g in phrases}
    accepted: list[dict] = []
    rejected: list[str] = []
    taken: list[dict] = list(entities)  # aliases accepted in this run count against later proposals
    tips = 0
    for item in items:
        kind = str(item.get("kind", ""))
        group = seen.get(norm(str(item.get("phrase", ""))))
        title = " ".join(str(item.get("title", "")).split())[:120]
        detail = " ".join(str(item.get("detail", "")).split())[:400]
        if group is None or not title:
            rejected.append(f"{item.get('title') or item.get('phrase')!r}: phrase not in the recent list")
            continue
        common = {"title": title, "detail": detail, "phrase": group["phrase"], "evidence": group["count"]}
        if kind == "alias":
            eid = str(item.get("entity_id", ""))
            try:
                alias = check_alias(str(item.get("alias", "")), eid, taken)
            except AliasError as exc:
                rejected.append(f"{item.get('alias')!r} -> {eid}: {exc}")
                continue
            if norm(alias) not in norm(group["phrase"]):
                rejected.append(f"{alias!r}: not part of the phrase that was said")
                continue
            target = next(e for e in taken if e["id"] == eid)
            target["aliases"] = [*target["aliases"], alias]  # block a duplicate alias in the same run
            accepted.append({**common, "kind": "alias", "entity_id": eid, "alias": alias,
                             "fingerprint": fingerprint("alias", eid, alias)})
        elif kind in ("automation", "scene"):
            try:
                plan = build_plan(kind, item, group["phrase"], entities)
            except PlanError as exc:
                rejected.append(f"{title!r}: {exc}")
                continue
            accepted.append({**common, "kind": kind, "entity_id": None, "alias": None, "payload": plan,
                             "fingerprint": fingerprint(kind, None, plan_fingerprint_text(kind, plan))})
        elif kind == "tip" and tips < MAX_TIPS:
            tips += 1
            accepted.append({**common, "kind": "tip", "entity_id": None, "alias": None,
                             "fingerprint": fingerprint("tip", None, title)})
        else:
            rejected.append(f"{title!r}: unsupported kind or too many tips")
        if len(accepted) >= MAX_SUGGESTIONS:
            break
    return accepted, rejected


class Analyzer:
    """Runs the analysis on demand and on a daily schedule."""

    def __init__(self, settings: Settings, store: Store, client: Any, budget: Budget | None = None):
        self.s = settings
        self.store = store
        self.client = client
        self.budget = budget
        self.running = False
        self._lock = asyncio.Lock()

    async def run(self, now: float | None = None) -> dict:
        """One analysis pass. Never raises: the outcome (including an error) is recorded and returned."""
        if self._lock.locked():
            return {"status": "busy"}
        async with self._lock:
            self.running = True
            try:
                return await self._run(now if now is not None else time.time())
            finally:
                self.running = False

    async def _run(self, now: float) -> dict:
        model = self.s.analysis_model
        interactions = self.store.interactions_since(now - self.s.analysis_days * 86400)
        phrases = summarize_phrases(interactions)
        if not phrases:
            return {"status": "nothing_to_analyze", "created": 0}
        if self.budget is not None and self.budget.exceeded():
            self.store.add_analysis_run(model=model, interactions=len(phrases), created=0, rejected=0,
                                        cost_usd=0.0, error="budget_exceeded")
            return {"status": "error", "error": "budget_exceeded"}
        usage = Usage()
        try:
            entities = await fetch_entities(self.s)
            response = await self.client.messages.create(
                model=model, max_tokens=8192, system=system_prompt(), tools=[REPORT_TOOL],
                output_config={"effort": "medium"},
                messages=[{"role": "user",
                           "content": build_prompt(phrases, entities, self.s.language)}])
            usage.add(response.usage)
            call = next((b for b in response.content if b.type == "tool_use"), None)
            items = list((call.input if call else {}).get("suggestions") or [])
            accepted, rejected = validate(items, phrases, entities)
            created = 0
            for s in accepted:
                if self.store.add_suggestion(**s, now=now) is not None:
                    created += 1
            cost = usage_record(model, usage)["cost_usd"]
            self.store.add_analysis_run(model=model, interactions=len(phrases), created=created,
                                        rejected=len(rejected), cost_usd=cost, ts=now)
            for reason in rejected:
                log.info("suggestion rejected: %s", reason)
            log.info("analysis: %d phrases, %d proposed, %d created, %d rejected",
                     len(phrases), len(items), created, len(rejected))
            return {"status": "ok", "created": created, "rejected": len(rejected), "cost_usd": cost}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log.error("analysis failed: %s", error)
            self.store.add_analysis_run(model=model, interactions=len(phrases), created=0, rejected=0,
                                        cost_usd=usage_record(model, usage)["cost_usd"], error=error, ts=now)
            return {"status": "error", "error": error}

    def due(self, now: float | None = None) -> bool:
        """True when the daily run is scheduled for this hour and has not run yet today (local time)."""
        if self.s.analysis_hour < 0:
            return False
        tz = ZoneInfo(self.s.timezone)
        moment = datetime.fromtimestamp(now if now is not None else time.time(), tz)
        if moment.hour != self.s.analysis_hour:
            return False
        last = self.store.last_analysis_run()
        return not (last and datetime.fromtimestamp(last["ts"], tz).date() == moment.date())

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                if self.due():
                    await self.run()
            except Exception:  # the schedule must outlive any single failure
                log.exception("scheduled analysis crashed")
