import json

import httpx
import pytest

from voice_assist_improver.analysis import summarize_phrases, validate
from voice_assist_improver.config import Settings
from voice_assist_improver.ha import automations
from voice_assist_improver.ha.automations import PlanError, build_plan
from voice_assist_improver.ha.ws import HAError
from voice_assist_improver.store import Store


def ent(eid, name, area="Sala", device_class=None):
    return {"id": eid, "domain": eid.split(".")[0], "name": name, "area": area, "aliases": [],
            "aliases_raw": [None], "device_class": device_class}


ENTITIES = [ent("light.pendente", "Sala Pendente"), ent("light.led", "Sala Led"),
            ent("climate.ar", "Ar da Sala"), ent("lock.porta", "Porta"),
            ent("cover.portao", "Portao", device_class="gate"), ent("switch.tv", "TV")]


def auto(**kw):
    return {"actions": [{"service": "light.turn_on", "entity_ids": ["light.pendente"],
                         "data": {"brightness_pct": 30}}], **kw}


# ---------- validation ----------


def test_automation_plan_is_built_with_the_users_phrase_as_first_sentence():
    plan = build_plan("automation", auto(sentences=["luz baixa na sala", "{wild} luz"], response="Pronto."),
                      "Deixa a luz da sala baixinha?", ENTITIES)
    assert plan["sentences"][0] == "Deixa a luz da sala baixinha"
    assert "luz baixa na sala" in plan["sentences"] and not any("{" in s for s in plan["sentences"])
    assert plan["actions"][0]["data"] == {"brightness_pct": 30}
    assert plan["plan"] == ["light.turn_on → Sala Pendente (brightness_pct 30)"]


@pytest.mark.parametrize("item, reason", [
    ({"actions": [{"service": "lock.unlock", "entity_ids": ["lock.porta"]}]}, "not allowed"),
    ({"actions": [{"service": "light.turn_on", "entity_ids": ["light.nope"]}]}, "not exposed"),
    ({"actions": [{"service": "light.turn_on", "entity_ids": ["light.led"], "data": {"brightness_pct": 400}}]},
     "between"),
    ({"actions": [{"service": "light.turn_on", "entity_ids": ["light.led"], "data": {"effect": "x"}}]},
     "not allowed"),
    ({"actions": [{"service": "light.turn_on", "entity_ids": ["switch.tv"]}]}, "not a light"),
    ({"actions": []}, "no actions"),
    (auto(response="Oi {{ states('x') }}"), "plain text"),
])
def test_automation_plan_rejections(item, reason):
    with pytest.raises(PlanError, match=reason):
        build_plan("automation", item, "frase", ENTITIES)


def test_scene_plan_and_its_limits():
    item = {"name": "Cinema", "states": [
        {"entity_id": "light.pendente", "state": "off"},
        {"entity_id": "light.led", "state": "on", "data": {"brightness_pct": 20, "color_temp_kelvin": 2700}},
        {"entity_id": "climate.ar", "state": "cool", "data": {"temperature": 22}}]}
    plan = build_plan("scene", item, "modo cinema", ENTITIES)
    assert plan["name"] == "Cinema" and len(plan["states"]) == 3
    with pytest.raises(PlanError, match="state must be"):
        build_plan("scene", {"name": "x1", "states": [{"entity_id": "light.led", "state": "open"}]}, "p", ENTITIES)
    with pytest.raises(PlanError, match="do not support"):
        build_plan("scene", {"name": "x1", "states": [{"entity_id": "media_player.x", "state": "on"}]}, "p",
                   [ent("media_player.x", "X")])


def test_exposure_is_the_gate_and_unsupported_domains_have_no_services():
    # What the user did not expose to Assist does not exist for the app...
    hidden = [e for e in ENTITIES if e["id"] != "light.pendente"]
    with pytest.raises(PlanError, match="not exposed"):
        build_plan("automation", auto(), "p", hidden)
    # ...and what is exposed is limited to the services the executors know how to validate: nothing for
    # locks or alarms, so no automation or scene can unlock a door even if it is exposed.
    for service in ("lock.unlock", "lock.lock", "alarm_control_panel.alarm_disarm"):
        with pytest.raises(PlanError, match="not allowed"):
            build_plan("automation", {"actions": [{"service": service, "entity_ids": ["lock.porta"]}]},
                       "p", ENTITIES)
    with pytest.raises(PlanError, match="do not support"):
        build_plan("scene", {"name": "Fechar", "states": [{"entity_id": "lock.porta", "state": "on"}]}, "p",
                   ENTITIES)


def test_validate_handles_the_new_kinds_and_rejects_bad_ones():
    rows = [{"ts": i, "utterance": "Modo cinema", "reply": "ok", "error": None, "tools": []} for i in range(3)]
    phrases = summarize_phrases(rows)
    items = [
        {"kind": "scene", "phrase": "Modo cinema", "title": "Cinema", "name": "Cinema",
         "states": [{"entity_id": "light.led", "state": "on", "data": {"brightness_pct": 10}}]},
        {"kind": "automation", "phrase": "Modo cinema", "title": "bad",
         "actions": [{"service": "lock.unlock", "entity_ids": ["lock.porta"]}]},
    ]
    accepted, rejected = validate(items, phrases, ENTITIES)
    assert [a["kind"] for a in accepted] == ["scene"] and accepted[0]["payload"]["sentences"] == ["Modo cinema"]
    assert accepted[0]["evidence"] == 3 and len(rejected) == 1


# ---------- executors against a fake Home Assistant ----------


class FakeHA:
    def __init__(self, fail_on=None):
        self.configs: dict[tuple[str, str], dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on

    def handler(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        self.calls.append((request.method, request.url.path))
        if request.url.path == "/api/states":
            return httpx.Response(200, json=[
                {"entity_id": f"scene.{k[1]}", "attributes": {"id": k[1]}}
                for k in self.configs if k[0] == "scene"])
        domain, config_id = parts[2], parts[4]
        key = (domain, config_id)
        if request.method == "POST":
            if self.fail_on == domain:
                return httpx.Response(400, text="invalid config")
            self.configs[key] = json.loads(request.content)
            return httpx.Response(200, json={"result": "ok"})
        if request.method == "GET":
            return httpx.Response(200, json=self.configs[key]) if key in self.configs else httpx.Response(404)
        if request.method == "DELETE":
            return httpx.Response(200 if self.configs.pop(key, None) is not None else 404)
        return httpx.Response(405)


def fake_client(ha):
    return httpx.AsyncClient(transport=httpx.MockTransport(ha.handler), base_url="http://ha")


def suggestion(kind, plan, sid=7):
    return {"id": sid, "kind": kind, "title": "Cinema", "payload": plan}


async def test_apply_automation_writes_a_sentence_trigger_and_undo_removes_it(tmp_path):
    settings = Settings(data_dir=tmp_path)
    plan = build_plan("automation", auto(response="Pronto."), "luz baixa", ENTITIES)
    ha = FakeHA()
    ref = await automations.apply_plan(settings, suggestion("automation", plan), plan, ENTITIES, fake_client(ha))
    config = ha.configs[("automation", ref["automation"])]
    assert config["triggers"] == [{"trigger": "conversation", "command": ["luz baixa"]}]
    assert config["actions"][0] == {"action": "light.turn_on", "target": {"entity_id": ["light.pendente"]},
                                    "data": {"brightness_pct": 30}}
    assert config["actions"][-1] == {"set_conversation_response": "Pronto."}
    assert "{{" not in json.dumps(config)
    await automations.undo_plan(settings, ref, fake_client(ha))
    assert not ha.configs
    await automations.undo_plan(settings, ref, fake_client(ha))  # idempotent


async def test_apply_scene_creates_the_scene_and_an_automation_that_activates_it(tmp_path):
    settings = Settings(data_dir=tmp_path)
    plan = build_plan("scene", {"name": "Cinema", "states": [
        {"entity_id": "light.led", "state": "on", "data": {"brightness_pct": 20}}]}, "modo cinema", ENTITIES)
    ha = FakeHA()
    ref = await automations.apply_plan(settings, suggestion("scene", plan, 9), plan, ENTITIES, fake_client(ha))
    scene = ha.configs[("scene", ref["scene"])]
    assert scene["entities"]["light.led"] == {"state": "on", "brightness": 51}
    action = ha.configs[("automation", ref["automation"])]["actions"][0]
    assert action == {"action": "scene.turn_on", "target": {"entity_id": f"scene.{ref['scene']}"}}
    await automations.undo_plan(settings, ref, fake_client(ha))
    assert not ha.configs


async def test_failed_write_leaves_nothing_behind(tmp_path):
    settings = Settings(data_dir=tmp_path)
    plan = build_plan("scene", {"name": "Cinema", "states": [{"entity_id": "light.led", "state": "off"}]},
                      "modo cinema", ENTITIES)
    ha = FakeHA(fail_on="automation")
    with pytest.raises(HAError, match="400"):
        await automations.apply_plan(settings, suggestion("scene", plan), plan, ENTITIES, fake_client(ha))
    assert not ha.configs  # the scene that was already written was rolled back


async def test_apply_revalidates_against_the_current_home(tmp_path):
    settings = Settings(data_dir=tmp_path)
    plan = build_plan("automation", auto(), "luz baixa", ENTITIES)
    still_there = [e for e in ENTITIES if e["id"] != "light.pendente"]  # no longer exposed
    with pytest.raises(HAError, match="no longer valid"):
        await automations.apply_plan(settings, suggestion("automation", plan), plan, still_there,
                                     fake_client(FakeHA()))


# ---------- through the UI API ----------


async def test_ui_apply_and_undo_an_automation_suggestion(tmp_path, monkeypatch):
    from voice_assist_improver import ui
    from voice_assist_improver.backends.unconfigured import UnconfiguredBackend
    from voice_assist_improver.ollama_api import create_app

    ha = FakeHA()
    real = automations._client
    monkeypatch.setattr(automations, "_client", lambda settings: fake_client(ha))
    assert real  # the real factory exists

    async def entities(_settings):
        return ENTITIES
    monkeypatch.setattr(ui, "fetch_entities", entities)

    s = Settings(data_dir=tmp_path)
    store = Store(tmp_path / "x.sqlite3")
    plan = build_plan("automation", auto(), "luz baixa", ENTITIES)
    sid = store.add_suggestion(fingerprint="f", kind="automation", title="Luz baixa", phrase="luz baixa",
                               evidence=3, payload=plan)
    app = create_app(s, UnconfiguredBackend(s, ""), store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                 base_url="http://app") as client:
        listed = (await client.get("/ui/api/suggestions")).json()["suggestions"][0]
        assert listed["plan"] and listed["sentences"] == ["luz baixa"] and listed["applied"] is False
        assert (await client.post(f"/ui/api/suggestions/{sid}/apply")).status_code == 200
        assert (await client.get("/ui/api/suggestions")).json()["suggestions"][0]["applied"] is True
        assert len(ha.configs) == 1
        assert (await client.post(f"/ui/api/suggestions/{sid}/undo")).status_code == 200
        assert not ha.configs and store.get_suggestion(sid)["status"] == "new"
        assert (await client.post(f"/ui/api/suggestions/{sid}/undo")).status_code == 400
    store.close()
