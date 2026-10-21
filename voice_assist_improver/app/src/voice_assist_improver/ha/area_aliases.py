"""Rule-based "thing in the area" aliases (no LLM involved).

Assist's local matching only understands an entity's exact name ("Sala Pendente"), but people say it the
natural way ("o pendente da sala"). For entities named "<Area> <thing>" or "<thing> <Area>" this proposes the
natural phrasing as an alias.

This is language-specific. English Assist sentences already understand "the <thing> in the <area>" natively,
so only pt-BR rules exist for now; other languages return no proposals.
"""
from __future__ import annotations

from ..i18n import normalize_language
from ..text import norm
from .aliases import AliasError, check_alias

DOMAINS = {"light", "fan", "cover", "valve"}
MIN_THING_LENGTH = 3
PT_FEMININE_AREAS = {"sala", "cozinha", "varanda", "garagem", "suite", "lavanderia"}
PT_PREPOSITIONS = {"da", "do", "de", "na", "no", "em", "das", "dos"}


def pt_preposition(area: str) -> str:
    key = norm(area)
    if key.startswith("quarto"):
        return "do"
    if key in PT_FEMININE_AREAS:
        return "da"
    return "da" if key.endswith("a") else "do"


def split_name(name: str, area: str) -> str | None:
    """The part of the name that is not the area, or None if it is not '<Area> thing' / 'thing <Area>'."""
    n, a = norm(name), norm(area)
    words, area_words = n.split(), a.split()
    k = len(area_words)
    original = name.split()
    thing = None
    if words[:k] == area_words and len(words) > k:
        thing = original[k:]
    elif words[-k:] == area_words and len(words) > k:
        thing = original[:-k]
    # "Ar da Suíte" is already natural; joining another preposition would produce "ar da da suíte".
    if not thing or norm(thing[-1]) in PT_PREPOSITIONS or norm(thing[0]) in PT_PREPOSITIONS:
        return None
    return " ".join(thing)


def generate(entities: list[dict], language: str = "pt-BR") -> list[dict]:
    """Valid, de-duplicated proposals: [{entity_id, alias, name}]."""
    if normalize_language(language) != "pt-BR":
        return []
    candidates = []
    for e in entities:
        if e["domain"] not in DOMAINS or not e.get("area"):
            continue
        thing = split_name(e["name"], e["area"])
        if not thing or len(norm(thing)) < MIN_THING_LENGTH:
            continue
        alias = f"{thing.strip().lower()} {pt_preposition(e['area'])} {e['area'].strip().lower()}"
        candidates.append({"entity_id": e["id"], "alias": alias, "name": e["name"]})
    counts: dict[str, int] = {}
    for c in candidates:
        counts[norm(c["alias"])] = counts.get(norm(c["alias"]), 0) + 1
    # A duplicate alias is ambiguous: keep neither.
    unique = [c for c in candidates if counts[norm(c["alias"])] == 1]
    accepted = []
    for c in unique:
        try:
            c["alias"] = check_alias(c["alias"], c["entity_id"], entities)
        except AliasError:
            continue
        accepted.append(c)
    return accepted
