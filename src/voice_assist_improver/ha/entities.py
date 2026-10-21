"""Entities exposed to Assist, with their aliases."""
from __future__ import annotations

from ..config import Settings
from .ws import connect

# Only these domains may ever receive aliases or be touched by suggestions. Locks, alarms, garage doors and
# gates are deliberately absent: the improver never helps voice-control them.
SAFE_DOMAINS = {"light", "switch", "climate", "cover", "fan", "valve", "media_player"}
BLOCKED_DEVICE_CLASSES = {"gate", "garage", "garage_door", "door"}


def is_safe(entity: dict) -> bool:
    return entity["domain"] in SAFE_DOMAINS and entity.get("device_class") not in BLOCKED_DEVICE_CLASSES


async def fetch_entities(settings: Settings) -> list[dict]:
    """Entities exposed to Assist: id, domain, name, area, device_class, aliases and aliases_raw.

    `aliases_raw` is the registry list as Home Assistant stores it, where None means "also answers to its
    own name". The registry *listing* does not include aliases at all; only get_entries does.
    """
    async with connect(settings) as ha:
        ents = await ha.call({"type": "config/entity_registry/list"})
        areas = {a["area_id"]: a["name"] for a in await ha.call({"type": "config/area_registry/list"})}
        devs = {d["id"]: d for d in await ha.call({"type": "config/device_registry/list"})}
        exposed = (await ha.call({"type": "homeassistant/expose_entity/list"}))["exposed_entities"]
        states = {s["entity_id"]: s for s in await ha.call({"type": "get_states"})}
        wanted = [e["entity_id"] for e in ents
                  if not e.get("disabled_by") and exposed.get(e["entity_id"], {}).get("conversation")]
        full = await ha.call({"type": "config/entity_registry/get_entries", "entity_ids": wanted})
    out = []
    wanted_set = set(wanted)
    for e in ents:
        eid = e["entity_id"]
        if eid not in wanted_set:
            continue
        raw = list((full.get(eid) or {}).get("aliases") or [])
        attrs = states.get(eid, {}).get("attributes", {})
        area = e.get("area_id") or devs.get(e.get("device_id"), {}).get("area_id")
        out.append({
            "id": eid, "domain": eid.split(".")[0], "area": areas.get(area),
            "name": attrs.get("friendly_name") or e.get("name") or e.get("original_name") or eid,
            "aliases": [a for a in raw if isinstance(a, str)], "aliases_raw": raw,
            "device_class": attrs.get("device_class") or e.get("original_device_class"),
        })
    return out
