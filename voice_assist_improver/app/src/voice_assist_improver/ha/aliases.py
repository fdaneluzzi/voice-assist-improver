"""Assist aliases: validate, add, remove and repair, with safety checks and an audit log.

An alias is an alternative name for an entity ("chandelier" for "Living Room Pendant") that Assist's local
matching understands, with no LLM involved. LLM output is only ever a *proposal*: this module validates it.

Home Assistant quirk that already cost us once: the registry's alias list is [None] for every entity, where
None means "also answers to its own name". Writing a list WITHOUT None makes the entity stop answering to
its own name. `with_alias` always preserves it, and `repair` fixes entities that lost it.
"""
from __future__ import annotations

import json
import re
import sys
import time

from ..config import Settings
from ..text import norm
from .entities import fetch_entities
from .ws import HAError, connect

MAX_ALIAS_LENGTH = 40


class AliasError(HAError):
    pass


def with_alias(raw: list, alias: str) -> list:
    """The registry alias list with `alias` added. Never drops the None marker."""
    base = list(raw) if None in raw else [None, *raw]
    return [*base, alias]


def without_alias(raw: list, alias: str) -> list:
    return [a for a in raw if a is None or norm(a) != norm(alias)]


def needs_repair(entity: dict) -> bool:
    """Has text aliases but lost the None marker, so Assist no longer understands its original name."""
    return bool(entity["aliases"]) and None not in entity["aliases_raw"]


def check_alias(alias: str, entity_id: str, entities: list[dict]) -> str:
    """Validate an alias against the exposed entities. Returns the cleaned alias or raises AliasError."""
    alias = " ".join(alias.split())
    target = next((e for e in entities if e["id"] == entity_id), None)
    if target is None:
        raise AliasError(f"{entity_id} is not exposed to Assist")
    if not (2 <= len(alias) <= MAX_ALIAS_LENGTH) or not re.search(r"[^\W\d_]", alias):
        raise AliasError("invalid alias (length, or no letters)")
    key = norm(alias)
    if not key:
        raise AliasError("invalid alias")
    if key in {norm(target["name"])} | {norm(a) for a in target["aliases"]}:
        raise AliasError("the entity already answers to that name")
    for e in entities:
        names = {norm(e["name"])} | {norm(a) for a in e["aliases"]}
        if e["area"]:
            names.add(norm(e["area"]))
        if e["id"] != entity_id and key in names:
            raise AliasError(f"ambiguous: '{alias}' already refers to {e['id']}")
    return alias


def _audit(settings: Settings, **record) -> None:
    path = settings.data_dir / "aliases_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}, ensure_ascii=False) + "\n")


async def apply_alias(settings: Settings, entity_id: str, alias: str) -> str:
    entities = await fetch_entities(settings)
    alias = check_alias(alias, entity_id, entities)
    target = next(e for e in entities if e["id"] == entity_id)
    async with connect(settings) as ha:
        await ha.call({"type": "config/entity_registry/update", "entity_id": entity_id,
                       "aliases": with_alias(target["aliases_raw"], alias)})
        after = (await ha.call({"type": "config/entity_registry/get", "entity_id": entity_id}))["aliases"]
    if alias not in after or None not in after:  # verify: the alias is in and the original name still works
        raise AliasError(f"Home Assistant did not confirm the alias (it is now {after})")
    _audit(settings, action="add", entity_id=entity_id, alias=alias, before=target["aliases_raw"])
    return f"alias '{alias}' added to {target['name']} ({entity_id})"


async def remove_alias(settings: Settings, entity_id: str, alias: str) -> str:
    entities = await fetch_entities(settings)
    target = next((e for e in entities if e["id"] == entity_id), None)
    if target is None:
        raise AliasError(f"{entity_id} not found")
    keep = without_alias(target["aliases_raw"], alias)
    if len(keep) == len(target["aliases_raw"]):
        raise AliasError("alias not found on that entity")
    async with connect(settings) as ha:
        await ha.call({"type": "config/entity_registry/update", "entity_id": entity_id, "aliases": keep})
    _audit(settings, action="remove", entity_id=entity_id, alias=alias, before=target["aliases_raw"])
    return f"alias '{alias}' removed from {target['name']}"


async def repair(settings: Settings) -> list[str]:
    """Give the None marker back to entities that have text aliases but lost it."""
    fixed = []
    entities = await fetch_entities(settings)
    async with connect(settings) as ha:
        for e in entities:
            if needs_repair(e):
                await ha.call({"type": "config/entity_registry/update", "entity_id": e["id"],
                               "aliases": [None, *e["aliases_raw"]]})
                _audit(settings, action="repair", entity_id=e["id"], before=e["aliases_raw"])
                fixed.append(e["id"])
    return fixed


async def apply_many(settings: Settings, items: list[dict]) -> tuple[list[str], list[str]]:
    """Apply several aliases over one connection. Each item goes through the same checks as apply_alias,
    including against aliases added earlier in the same batch. Returns (applied, rejected)."""
    entities = await fetch_entities(settings)
    by_id = {e["id"]: e for e in entities}
    done, skipped = [], []
    async with connect(settings) as ha:
        for item in items:
            eid, raw_alias = str(item.get("entity_id", "")), str(item.get("alias", ""))
            try:
                alias = check_alias(raw_alias, eid, entities)
                target = by_id[eid]
                await ha.call({"type": "config/entity_registry/update", "entity_id": eid,
                               "aliases": with_alias(target["aliases_raw"], alias)})
            except AliasError as exc:
                skipped.append(f"{raw_alias!r} -> {eid}: {exc}")
                continue
            target["aliases_raw"] = with_alias(target["aliases_raw"], alias)
            target["aliases"] = [*target["aliases"], alias]
            _audit(settings, action="add", entity_id=eid, alias=alias, bulk=True)
            done.append(f"{alias} -> {target['name']}")
    return done, skipped


def main(argv: list[str] | None = None) -> int:
    import asyncio

    argv = argv if argv is not None else sys.argv[1:]
    settings = Settings.load()
    try:
        if len(argv) == 3 and argv[0] in ("apply", "remove"):
            fn = apply_alias if argv[0] == "apply" else remove_alias
            print("OK: " + asyncio.run(fn(settings, argv[1], argv[2])))
            return 0
        if argv == ["apply-bulk"]:
            done, skipped = asyncio.run(apply_many(settings, json.load(sys.stdin)))
            note = f"; {len(skipped)} rejected: " + "; ".join(skipped[:3]) if skipped else ""
            print(f"OK: {len(done)} alias(es) applied{note}")
            return 0
        if argv == ["repair"]:
            fixed = asyncio.run(repair(settings))
            print(f"OK: {len(fixed)} entity(ies) repaired" if fixed else "OK: nothing to repair")
            return 0
        if argv == ["list"]:
            for e in asyncio.run(fetch_entities(settings)):
                if e["aliases"]:
                    print(e["id"], "->", e["aliases"])
            return 0
    except HAError as exc:
        print(f"ERROR: {exc}")
        return 1
    print("usage: python -m voice_assist_improver.ha.aliases "
          "apply|remove <entity_id> <alias> | apply-bulk (JSON on stdin) | repair | list")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
