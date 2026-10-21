import pytest

from voice_assist_improver.ha.aliases import AliasError, check_alias, needs_repair, with_alias, without_alias

ENTITIES = [
    {"id": "light.pendant", "domain": "light", "name": "Sala Pendente", "area": "Sala", "aliases": ["chandelier"], "device_class": None},
    {"id": "light.led", "domain": "light", "name": "Sala Led", "area": "Sala", "aliases": [], "device_class": None},
    {"id": "climate.ac", "domain": "climate", "name": "Ar da suíte", "area": "Suite", "aliases": [], "device_class": None},
    {"id": "cover.gate", "domain": "cover", "name": "Gate", "area": "Garage", "aliases": [], "device_class": "gate"},
    {"id": "lock.door", "domain": "lock", "name": "Door", "area": None, "aliases": [], "device_class": None},
]


def test_accepts_a_clean_alias():
    assert check_alias("  light   above ", "light.pendant", ENTITIES) == "light above"


@pytest.mark.parametrize("alias,entity,message", [
    ("chandelier", "light.pendant", "already answers"),
    ("Sala Pendente", "light.pendant", "already answers"),
    ("sala", "light.led", "ambiguous"),
    ("sala pendente", "light.led", "ambiguous"),
    ("chandelier", "light.led", "ambiguous"),
    ("x", "light.led", "invalid"),
    ("123", "light.led", "invalid"),
    ("a" * 41, "light.led", "invalid"),
])
def test_rejects_bad_aliases(alias, entity, message):
    with pytest.raises(AliasError, match=message):
        check_alias(alias, entity, ENTITIES)


def test_rejects_entities_that_are_not_exposed_to_assist():
    with pytest.raises(AliasError, match="not exposed"):
        check_alias("open everything", "light.unknown", ENTITIES)


def test_exposure_in_home_assistant_is_the_gate_not_a_domain_list():
    # Whatever the user exposed to Assist may get an alias; what is not exposed does not exist for the app.
    assert check_alias("front door", "lock.door", ENTITIES) == "front door"


def test_with_alias_never_drops_the_default_name_marker():
    # None = "the entity also answers to its own name"; without it Assist loses the original name.
    assert with_alias([None], "chandelier") == [None, "chandelier"]
    assert with_alias([], "chandelier") == [None, "chandelier"]  # repairs lists that already lost it
    assert with_alias([None, "a"], "b") == [None, "a", "b"]


def test_without_alias_keeps_the_marker_and_other_aliases():
    assert without_alias([None, "chandelier", "a"], "Chandelier") == [None, "a"]
    assert without_alias([None], "x") == [None]


def test_needs_repair_only_for_text_aliases_without_none():
    assert needs_repair({"aliases": ["a"], "aliases_raw": ["a"]})
    assert not needs_repair({"aliases": ["a"], "aliases_raw": [None, "a"]})
    assert not needs_repair({"aliases": [], "aliases_raw": [None]})
    assert not needs_repair({"aliases": [], "aliases_raw": []})
