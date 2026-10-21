"""Sentence-triggered automations and scenes: validated plans and deterministic executors.

A model may *propose* an automation ("when someone says X, do Y") or a scene, but it never writes Home
Assistant configuration. A proposal is turned into a plan by `build_plan`, which only accepts:

- entities that are exposed to Assist and allowed by the user's policy (no locks/alarms/gates by default),
- services from a small allow-list per domain, with typed and range-checked data,
- plain sentences (no wildcards, no templates anywhere).

The executors write through Home Assistant's own configuration API, verify what was written, and can undo it.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

import httpx

from ..config import Settings
from ..policy import DEFAULT_POLICY, Policy
from ..text import norm
from .aliases import _audit
from .ws import HAError

MAX_SENTENCES = 4
MAX_ACTIONS = 6
MAX_ENTITIES_PER_ACTION = 8
MAX_SCENE_ENTITIES = 20
MAX_SENTENCE_LENGTH = 80
MAX_RESPONSE_LENGTH = 120
ID_PREFIX = "vai_"

HVAC_MODES = ("off", "heat", "cool", "auto", "heat_cool", "dry", "fan_only")

# domain -> service -> allowed data keys with (type, minimum, maximum) or ("enum", values)
SERVICES: dict[str, dict[str, dict[str, tuple]]] = {
    "light": {
        "turn_on": {"brightness_pct": ("int", 0, 100), "color_temp_kelvin": ("int", 1500, 9000),
                    "transition": ("int", 0, 300)},
        "turn_off": {"transition": ("int", 0, 300)},
        "toggle": {},
    },
    "switch": {"turn_on": {}, "turn_off": {}, "toggle": {}},
    "fan": {"turn_on": {}, "turn_off": {}, "toggle": {}, "set_percentage": {"percentage": ("int", 0, 100)}},
    "cover": {"open_cover": {}, "close_cover": {}, "stop_cover": {},
              "set_cover_position": {"position": ("int", 0, 100)}},
    "climate": {
        "turn_on": {}, "turn_off": {}, "set_temperature": {"temperature": ("float", 5, 35)},
        "set_hvac_mode": {"hvac_mode": ("enum", HVAC_MODES)},
    },
    "media_player": {"turn_on": {}, "turn_off": {}, "media_play": {}, "media_pause": {}, "media_stop": {},
                     "volume_set": {"volume_level": ("float", 0, 1)}},
    "valve": {"open_valve": {}, "close_valve": {}},
}

# Scene entity states: domain -> (allowed states, allowed attributes). Brightness is given as a percentage.
SCENE_STATES: dict[str, tuple[tuple[str, ...], dict[str, tuple]]] = {
    "light": (("on", "off"), {"brightness_pct": ("int", 1, 100), "color_temp_kelvin": ("int", 1500, 9000)}),
    "switch": (("on", "off"), {}),
    "fan": (("on", "off"), {"percentage": ("int", 0, 100)}),
    "cover": (("open", "closed"), {"position": ("int", 0, 100)}),
    "climate": (HVAC_MODES, {"temperature": ("float", 5, 35)}),
}

def describe_services() -> str:
    """The service allow-list as one line for the model, generated so it cannot drift from the code."""
    parts = []
    for domain, services in SERVICES.items():
        for name, spec in services.items():
            keys = ", ".join(spec)
            parts.append(f"{domain}.{name}" + (f" ({keys})" if keys else ""))
    return "; ".join(parts)


SENTENCE_CHARS = re.compile(r"[^\w\s,'’\-.?!]", re.UNICODE)


class PlanError(Exception):
    """A proposal that failed validation. The message says why (shown in logs, never applied)."""


# ---------- validation ----------


def _number(value: Any, kind: str, lo: float, hi: float, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(f"{name} must be a number")
    if not lo <= value <= hi:
        raise PlanError(f"{name} must be between {lo} and {hi}")
    return int(round(value)) if kind == "int" else float(value)


def _check_data(spec: dict[str, tuple], data: Any, where: str) -> dict:
    if data in (None, {}):
        return {}
    if not isinstance(data, dict):
        raise PlanError(f"{where}: data must be an object")
    clean: dict = {}
    for key, value in data.items():
        if key not in spec:
            raise PlanError(f"{where}: '{key}' is not allowed")
        kind, *rest = spec[key]
        if kind == "enum":
            if value not in rest[0]:
                raise PlanError(f"{where}: '{key}' must be one of {', '.join(rest[0])}")
            clean[key] = value
        else:
            clean[key] = _number(value, kind, rest[0], rest[1], f"{where}: {key}")
    return clean


def clean_sentence(text: str) -> str:
    """A plain trigger sentence: letters, digits, spaces and light punctuation only (no wildcards)."""
    cleaned = " ".join(SENTENCE_CHARS.sub(" ", str(text)).split()).strip(" ,.?!-")
    if not norm(cleaned) or len(cleaned) > MAX_SENTENCE_LENGTH:
        raise PlanError(f"unusable sentence {text!r}")
    return cleaned


def clean_sentences(user_phrase: str, extra: Any) -> list[str]:
    """The user's own phrase first (that is what repeats), then up to three variants from the model."""
    out = [clean_sentence(user_phrase)]
    for item in (extra if isinstance(extra, list) else [])[: MAX_SENTENCES - 1]:
        try:
            sentence = clean_sentence(item)
        except PlanError:
            continue
        if norm(sentence) not in {norm(s) for s in out}:
            out.append(sentence)
    return out


def _clean_response(value: Any) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    if "{" in text or "}" in text:
        raise PlanError("the spoken response must be plain text")
    return text[:MAX_RESPONSE_LENGTH] or None


def _entity(entities_by_id: dict[str, dict], entity_id: Any, policy: Policy,
            domain: str | None = None) -> dict:
    entity = entities_by_id.get(str(entity_id))
    if entity is None:
        raise PlanError(f"{entity_id} is not exposed to Assist")
    if not policy.allows(entity):
        raise PlanError(f"{entity_id} is not allowed by the policy")
    if domain and entity["domain"] != domain:
        raise PlanError(f"{entity_id} is not a {domain}")
    return entity


def _plan_actions(raw: Any, entities_by_id: dict[str, dict], policy: Policy) -> tuple[list[dict], list[str]]:
    if not isinstance(raw, list) or not raw:
        raise PlanError("no actions")
    actions, lines = [], []
    for i, item in enumerate(raw[:MAX_ACTIONS], 1):
        if not isinstance(item, dict):
            raise PlanError(f"action {i} is not an object")
        service = str(item.get("service", ""))
        domain, _, name = service.partition(".")
        spec = SERVICES.get(domain, {}).get(name)
        if spec is None:
            raise PlanError(f"service {service!r} is not allowed")
        ids = item.get("entity_ids") or []
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_ENTITIES_PER_ACTION:
            raise PlanError(f"action {i}: needs 1 to {MAX_ENTITIES_PER_ACTION} entities")
        ents = [_entity(entities_by_id, e, policy, domain) for e in ids]
        data = _check_data(spec, item.get("data"), f"action {i}")
        actions.append({"service": service, "entity_ids": [e["id"] for e in ents], "data": data})
        detail = ", ".join(f"{k} {v}" for k, v in data.items())
        lines.append(f"{service} → {', '.join(e['name'] for e in ents)}" + (f" ({detail})" if detail else ""))
    return actions, lines


def _scene_states(raw: Any, entities_by_id: dict[str, dict], policy: Policy) -> tuple[list[dict], list[str]]:
    if not isinstance(raw, list) or not raw:
        raise PlanError("a scene needs entity states")
    states, lines = [], []
    for item in raw[:MAX_SCENE_ENTITIES]:
        if not isinstance(item, dict):
            raise PlanError("a scene state is not an object")
        entity = _entity(entities_by_id, item.get("entity_id"), policy)
        allowed = SCENE_STATES.get(entity["domain"])
        if allowed is None:
            raise PlanError(f"{entity['id']}: scenes do not support {entity['domain']}")
        state = item.get("state")
        if state not in allowed[0]:
            raise PlanError(f"{entity['id']}: state must be one of {', '.join(allowed[0])}")
        data = _check_data(allowed[1], item.get("data"), entity["id"])
        states.append({"entity_id": entity["id"], "state": state, "data": data})
        detail = ", ".join(f"{k} {v}" for k, v in data.items())
        lines.append(f"{entity['name']}: {state}" + (f" ({detail})" if detail else ""))
    return states, lines


def build_plan(kind: str, item: dict, user_phrase: str, entities: list[dict],
               policy: Policy = DEFAULT_POLICY) -> dict:
    """Validate a model proposal and return the plan to store: {"sentences", "response", "plan", ...}.

    Raises PlanError with the reason when anything is not acceptable.
    """
    by_id = {e["id"]: e for e in entities}
    sentences = clean_sentences(user_phrase, item.get("sentences"))
    response = _clean_response(item.get("response"))
    if kind == "automation":
        actions, lines = _plan_actions(item.get("actions"), by_id, policy)
        return {"sentences": sentences, "response": response, "actions": actions, "plan": lines}
    if kind == "scene":
        name = " ".join(str(item.get("name", "")).split())[:60]
        if len(norm(name)) < 2:
            raise PlanError("a scene needs a name")
        states, lines = _scene_states(item.get("states"), by_id, policy)
        return {"sentences": sentences, "response": response, "name": name, "states": states, "plan": lines}
    raise PlanError(f"unsupported kind {kind!r}")


def plan_fingerprint_text(kind: str, plan: dict) -> str:
    """What identifies a plan for de-duplication, independent of wording."""
    core = plan.get("actions") if kind == "automation" else {"n": plan.get("name"), "s": plan.get("states")}
    return norm(plan["sentences"][0]) + "|" + hashlib.sha1(repr(core).encode()).hexdigest()[:12]


# ---------- Home Assistant configuration ----------


def automation_config(plan: dict, title: str, suggestion_id: int, scene_entity: str | None = None) -> dict:
    if scene_entity:
        actions: list[dict] = [{"action": "scene.turn_on", "target": {"entity_id": scene_entity}}]
    else:
        actions = []
        for a in plan["actions"]:
            step: dict = {"action": a["service"], "target": {"entity_id": a["entity_ids"]}}
            if a["data"]:
                step["data"] = a["data"]
            actions.append(step)
    if plan.get("response"):
        actions.append({"set_conversation_response": plan["response"]})
    return {
        "alias": f"Voice Assist Improver: {title}"[:100],
        "description": f"Created by Voice Assist Improver (suggestion {suggestion_id}). Delete it to undo.",
        "mode": "single",
        "triggers": [{"trigger": "conversation", "command": plan["sentences"]}],
        "conditions": [],
        "actions": actions,
    }


def scene_config(plan: dict, scene_id: str) -> dict:
    entities: dict[str, dict] = {}
    for s in plan["states"]:
        attrs: dict = {"state": s["state"]}
        data = s["data"]
        if "brightness_pct" in data:
            attrs["brightness"] = round(data["brightness_pct"] * 2.55)
        for key in ("color_temp_kelvin", "percentage", "temperature"):
            if key in data:
                attrs[key] = data[key]
        if "position" in data:
            attrs["current_position"] = data["position"]
        entities[s["entity_id"]] = attrs
    return {"id": scene_id, "name": plan["name"], "entities": entities}


def _client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.ha_url, timeout=20,
                             headers={"Authorization": f"Bearer {settings.ha_token}"})


async def _call(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise HAError(f"could not reach Home Assistant: {type(exc).__name__}") from exc
    if response.status_code >= 400 and not (method in ("GET", "DELETE") and response.status_code == 404):
        raise HAError(f"Home Assistant answered {response.status_code}: {response.text[:200]}")
    return response


async def _write(client: httpx.AsyncClient, domain: str, config_id: str, config: dict) -> None:
    await _call(client, "POST", f"/api/config/{domain}/config/{config_id}", json=config)
    check = await _call(client, "GET", f"/api/config/{domain}/config/{config_id}")
    if check.status_code != 200:
        raise HAError(f"Home Assistant did not confirm the {domain} ({check.status_code})")


async def _remove(client: httpx.AsyncClient, domain: str, config_id: str) -> None:
    gone = await _call(client, "DELETE", f"/api/config/{domain}/config/{config_id}")
    if gone.status_code == 404:
        return  # already gone: undo is idempotent


async def _scene_entity(client: httpx.AsyncClient, scene_id: str, tries: int = 10) -> str:
    """The entity id Home Assistant gave the scene, found by its configuration id."""
    for _ in range(tries):
        states = (await _call(client, "GET", "/api/states")).json()
        for state in states:
            if state["entity_id"].startswith("scene.") and state.get("attributes", {}).get("id") == scene_id:
                return state["entity_id"]
        await asyncio.sleep(0.5)
    raise HAError("the scene was written but did not appear in Home Assistant")


async def apply_plan(settings: Settings, suggestion: dict, plan: dict, entities: list[dict],
                     client: httpx.AsyncClient | None = None) -> dict:
    """Create what the plan describes. Re-validates first (the home may have changed since the analysis).

    Returns a reference {"automation": id, "scene": id | None} that `undo_plan` takes.
    """
    kind, sid = suggestion["kind"], int(suggestion["id"])
    # Re-validate against the current entities and the current policy.
    item = {"sentences": plan["sentences"][1:], "response": plan.get("response"),
            "actions": [{"service": a["service"], "entity_ids": a["entity_ids"], "data": a["data"]}
                        for a in plan.get("actions", [])],
            "name": plan.get("name"), "states": plan.get("states")}
    try:
        build_plan(kind, item, plan["sentences"][0], entities, settings.policy)
    except PlanError as exc:
        raise HAError(f"the plan is no longer valid: {exc}") from exc

    own = client or _client(settings)
    ref: dict = {"automation": f"{ID_PREFIX}auto_{sid}", "scene": None}
    try:
        if kind == "scene":
            ref["scene"] = f"{ID_PREFIX}scene_{sid}"
            await _write(own, "scene", ref["scene"], scene_config(plan, ref["scene"]))
            scene_entity = await _scene_entity(own, ref["scene"])
            config = automation_config(plan, suggestion["title"], sid, scene_entity)
        else:
            config = automation_config(plan, suggestion["title"], sid)
        await _write(own, "automation", ref["automation"], config)
    except Exception:
        for domain in ("automation", "scene"):  # leave nothing half-created
            if ref.get(domain):
                try:
                    await _remove(own, domain, ref[domain])
                except HAError:
                    pass
        raise
    finally:
        if client is None:
            await own.aclose()
    _audit(settings, action="create_" + kind, suggestion=sid, ref=ref, sentences=plan["sentences"])
    return ref


async def undo_plan(settings: Settings, ref: dict, client: httpx.AsyncClient | None = None) -> None:
    own = client or _client(settings)
    try:
        for domain in ("automation", "scene"):
            if ref.get(domain):
                await _remove(own, domain, ref[domain])
    finally:
        if client is None:
            await own.aclose()
    _audit(settings, action="undo", ref=ref)
