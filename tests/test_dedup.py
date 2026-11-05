import json

import httpx
import pytest
from test_automations import ENTITIES, FakeHA, auto, ent, fake_client

from voice_assist_improver.analysis import build_prompt, fingerprint, recent_rejections, validate
from voice_assist_improver.config import Settings
from voice_assist_improver.ha import automations
from voice_assist_improver.ha.automations import PlanError, build_plan, plan_fingerprint_text
from voice_assist_improver.store import DISMISS_QUIET_DAYS, Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "d.sqlite3")
    yield s
    s.close()


def command(phrase, *variants, entities=("light.pendente",), kind="automation"):
    item = {"actions": [{"service": "light.turn_off", "entity_ids": list(entities)}],
            "sentences": list(variants)}
    return build_plan(kind, item, phrase, ENTITIES)


def add(store, plan, fp, phrase="p", kind="automation", **kw):
    return store.add_suggestion(fingerprint=fp, kind=kind, title="t", phrase=phrase, evidence=2,
                                payload=plan, **kw)


def test_fingerprint_follows_the_phrase_not_the_entities_the_model_picked():
    a = command("Desligar tudo da varanda", entities=("light.pendente",))
    b = command("Desligar tudo da varanda.", entities=("light.pendente", "light.led"))
    assert plan_fingerprint_text("automation", a) == plan_fingerprint_text("automation", b)
    assert fingerprint("automation", None, plan_fingerprint_text("automation", a)) == \
        fingerprint("automation", None, plan_fingerprint_text("automation", b))


def test_a_command_sharing_a_trigger_sentence_is_a_duplicate_even_with_another_fingerprint(store):
    first = command("Desligar tudo da varanda", "Desliga tudo da varanda")
    assert add(store, first, "old-style-1")
    # a later analysis words it differently and (as in the old scheme) gets another fingerprint
    again = command("Desliga tudo da varanda", entities=("light.led",))
    assert add(store, again, "old-style-2") is None
    assert len(store.list_suggestions()) == 1


def test_duplicates_are_blocked_across_automation_and_scene(store):
    assert add(store, command("modo cinema", "filme"), "a")
    scene = build_plan("scene", {"name": "Cinema", "sentences": ["Filme"],
                                 "states": [{"entity_id": "light.led", "state": "off"}]}, "modo cinema", ENTITIES)
    assert add(store, scene, "b", kind="scene") is None


def test_unrelated_commands_are_both_kept(store):
    assert add(store, command("desligar a varanda"), "a")
    assert add(store, command("apagar o escritório"), "b")


def test_a_done_or_blocked_command_is_not_suggested_again_under_other_wording(store):
    sid = add(store, command("desligar tudo do escritório", "desliga tudo do escritório"), "a")
    store.set_suggestion_status(sid, "done")
    assert add(store, command("desliga tudo do escritório"), "b") is None
    store.set_suggestion_status(sid, "never")
    assert add(store, command("desliga tudo do escritório"), "c", now=9e12) is None


def test_a_dismissed_command_comes_back_once_as_the_same_suggestion(store):
    sid = add(store, command("luz baixa"), "a", now=1000)
    store.set_suggestion_status(sid, "dismissed", now=1000)
    later = 1000 + (DISMISS_QUIET_DAYS + 1) * 86400
    assert add(store, command("luz baixa"), "z", now=later - 86400 * 2) is None
    assert add(store, command("luz baixa"), "z", now=later) == sid
    assert len(store.list_suggestions()) == 1 and store.get_suggestion(sid)["status"] == "new"


def test_known_suggestions_lists_what_the_analysis_must_not_repeat(store):
    keep = add(store, command("luz baixa", "luz fraca"), "a", now=1000)
    old = add(store, command("apagar tudo"), "b", now=1000)
    store.set_suggestion_status(old, "dismissed", now=1000)
    names = [k["sentences"] for k in store.known_suggestions(now=1000 + 86400)]
    assert ["luz baixa", "luz fraca"] in names and ["apagar tudo"] in names
    later = 1000 + (DISMISS_QUIET_DAYS + 1) * 86400
    assert [k["sentences"] for k in store.known_suggestions(now=later)] == [["luz baixa", "luz fraca"]]
    assert keep


def test_validate_gives_the_same_fingerprint_on_every_run():
    phrases = [{"phrase": "Desligar tudo da varanda", "count": 2, "reply": "", "tools": [], "last": 1}]
    item = lambda ids: {"kind": "automation", "phrase": "Desligar tudo da varanda", "title": "t",  # noqa: E731
                        "actions": [{"service": "light.turn_off", "entity_ids": ids}]}
    one, _ = validate([item(["light.pendente"])], phrases, ENTITIES)
    two, _ = validate([item(["light.pendente", "light.led"])], phrases, ENTITIES)
    assert one[0]["fingerprint"] == two[0]["fingerprint"]


def test_nine_air_conditioners_fit_in_one_action_but_not_a_flood():
    many = [ent(f"climate.ar{i}", f"Ar {i}") for i in range(25)]
    ok = {"actions": [{"service": "climate.turn_off", "entity_ids": [e["id"] for e in many[:9]]}]}
    assert len(build_plan("automation", ok, "desligar todos os ares", many)["actions"][0]["entity_ids"]) == 9
    with pytest.raises(PlanError, match="needs 1 to 20"):
        build_plan("automation", {"actions": [{"service": "climate.turn_off",
                                               "entity_ids": [e["id"] for e in many[:21]]}]}, "x", many)


def test_prompt_carries_what_is_known_and_what_was_rejected():
    phrases = [{"phrase": "oi", "count": 1, "reply": "", "tools": [], "last": 1}]
    known = [{"status": "done", "kind": "automation", "phrase": "p", "title": "t", "alias": None,
              "entity_id": None, "sentences": ["desliga tudo do escritório", "apague tudo do escritório"]},
             {"status": "new", "kind": "alias", "phrase": "p", "title": "t", "alias": "pendente da sala",
              "entity_id": "light.pendente", "sentences": []}]
    text = build_prompt(phrases, ENTITIES, "pt-BR", known, ["'x': needs 1 to 8 entities"])
    assert "done | automation | desliga tudo do escritório; apague tudo do escritório" in text
    assert "new | alias | alias 'pendente da sala' -> light.pendente" in text
    assert "## Proposals rejected in recent runs" in text and "needs 1 to 8 entities" in text
    assert "Already suggested" not in build_prompt(phrases, ENTITIES, "en")


def test_recent_rejections_are_distinct_newest_first():
    runs = [{"rejections": ["a", "b"]}, {"rejections": ["b", "c"]}, {"rejections": None}, {}]
    assert recent_rejections(runs) == ["a", "b", "c"]


async def test_apply_is_refused_when_another_suggestion_already_created_the_same_command(tmp_path, monkeypatch):
    from voice_assist_improver import ui
    from voice_assist_improver.backends.unconfigured import UnconfiguredBackend
    from voice_assist_improver.ollama_api import create_app

    ha = FakeHA()
    monkeypatch.setattr(automations, "_client", lambda settings: fake_client(ha))

    async def entities(_settings):
        return ENTITIES
    monkeypatch.setattr(ui, "fetch_entities", entities)

    s = Settings(data_dir=tmp_path)
    store = Store(tmp_path / "x.sqlite3")
    first = command("desliga tudo do escritório")
    one = add(store, first, "f1")
    # a leftover from the old scheme: the same sentence under a different fingerprint, still "new"
    two = store._db.execute(
        "INSERT INTO suggestions (fingerprint, kind, phrase, title, evidence, payload, created, updated)"
        " VALUES ('f2','automation','p','t',1,?,1,1)", (json.dumps(command("desliga tudo do escritório")),)
    ).lastrowid
    store._db.commit()
    app = create_app(s, UnconfiguredBackend(s, ""), store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                 base_url="http://app") as client:
        assert (await client.post(f"/ui/api/suggestions/{one}/apply")).status_code == 200
        refused = await client.post(f"/ui/api/suggestions/{two}/apply")
        assert refused.status_code == 409 and f"#{one}" in refused.json()["detail"]
        assert len(ha.configs) == 1
        # after an undo the sentence is free again
        assert (await client.post(f"/ui/api/suggestions/{one}/undo")).status_code == 200
        assert (await client.post(f"/ui/api/suggestions/{two}/apply")).status_code == 200
    store.close()


def test_auto_helper_still_builds():  # guards the shared test helpers used above
    assert auto()["actions"]


async def test_analyzer_tells_the_model_what_exists_and_what_failed_and_stores_the_rejections(
        store, monkeypatch):
    import types

    from test_options_and_suggestions import ENTITIES as HOME
    from test_options_and_suggestions import FakeMessages

    from voice_assist_improver import analysis
    from voice_assist_improver.analysis import Analyzer

    async def fetch(_settings):
        return json.loads(json.dumps(HOME))
    monkeypatch.setattr(analysis, "fetch_entities", fetch)
    store.add_interaction(utterance="Desligar todos os ares")
    add(store, command("desliga tudo do escritório"), "a")
    store.add_analysis_run(model="m", interactions=1, created=0, rejected=1, cost_usd=0,
                           rejections=["'Todos os ares': action 1: needs 1 to 8 entities"])
    bad = {"kind": "automation", "phrase": "Desligar todos os ares", "title": "Todos os ares",
           "actions": [{"service": "climate.turn_off", "entity_ids": ["climate.nope"]}]}
    client = types.SimpleNamespace(messages=FakeMessages([bad]))
    await Analyzer(Settings(), store, client).run()
    prompt = client.messages.kwargs["messages"][0]["content"]
    assert "desliga tudo do escritório" in prompt and "needs 1 to 8 entities" in prompt
    assert any("not exposed" in r for r in store.recent_analysis_runs(1)[0]["rejections"])
