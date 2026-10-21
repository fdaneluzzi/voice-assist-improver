import json
import types

import httpx
import pytest

from voice_assist_improver import analysis
from voice_assist_improver.analysis import Analyzer, fingerprint, summarize_phrases, validate
from voice_assist_improver.backends.unconfigured import UnconfiguredBackend
from voice_assist_improver.config import Settings
from voice_assist_improver.ollama_api import create_app
from voice_assist_improver.store import Store

# ---------- options and add-on defaults ----------


def test_options_file_overrides_defaults_and_env_wins(tmp_path):
    opts = tmp_path / "options.json"
    opts.write_text(json.dumps({
        "anthropic_api_key": "sk-ant-x", "language": "pt-BR", "web_search": True,
        "monthly_budget_usd": 3, "voice_tool_denylist": ["a__*", "b__*"], "voice_token": "tok", "empty": ""}))
    s = Settings.load(env_file=str(tmp_path / "none"), environ={}, options_file=str(opts))
    assert s.anthropic_api_key == "sk-ant-x" and s.language == "pt-BR" and s.web_search is True
    assert s.monthly_budget_usd == 3 and s.voice_tool_denylist == ("a__*", "b__*")
    assert s.ha_mcp_token == "tok"
    s = Settings.load(env_file=str(tmp_path / "none"), environ={"VAI_LANGUAGE": "en"}, options_file=str(opts))
    assert s.language == "en"


def test_addon_mode_uses_supervisor_proxy_and_internal_networks(tmp_path):
    env = {"SUPERVISOR_TOKEN": "tok-secret-9"}
    s = Settings.load(env_file=str(tmp_path / "none"), environ=env, options_file=str(tmp_path / "none"))
    assert s.is_addon and s.ha_url == "http://supervisor/core" and s.ha_token == "tok-secret-9"
    assert s.ha_mcp_url == "http://supervisor/core/api/mcp"
    assert "172.30.32.0/23" in s.allowed_networks and s.ui_networks[0] == "172.30.32.2/32"
    assert s.backend == "anthropic" and str(s.data_dir) == "/data"
    assert "tok-secret-9" not in repr(s)


def test_missing_or_broken_options_file_is_ignored(tmp_path):
    bad = tmp_path / "options.json"
    bad.write_text("{not json")
    assert Settings.load(env_file=str(tmp_path / "none"), environ={}, options_file=str(bad)).language == "en"


# ---------- store: suggestions lifecycle ----------


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "s.sqlite3")
    yield s
    s.close()


def add(store, fp="f1", **kw):
    return store.add_suggestion(fingerprint=fp, kind="alias", title="t", entity_id="light.a", alias="x",
                                phrase="p", evidence=2, **kw)


def test_suggestion_not_recreated_when_new_done_or_never(store):
    sid = add(store)
    assert sid and add(store) is None
    store.set_suggestion_status(sid, "done")
    assert add(store) is None
    store.set_suggestion_status(sid, "never")
    assert add(store, now=9e12) is None  # blocked forever, however much time passes


def test_dismissed_suggestion_comes_back_only_after_the_quiet_period(store):
    sid = add(store, now=1000)
    store.set_suggestion_status(sid, "dismissed", now=1000)
    assert add(store, now=1000 + 29 * 86400) is None
    assert add(store, now=1000 + 31 * 86400) == sid
    assert store.get_suggestion(sid)["status"] == "new"


def test_unknown_status_rejected(store):
    sid = add(store)
    with pytest.raises(ValueError):
        store.set_suggestion_status(sid, "bogus")


def test_month_cost_includes_analysis_runs(store):
    store.add_interaction(utterance="a", usage={"cost_usd": 0.01})
    store.add_analysis_run(model="m", interactions=1, created=0, rejected=0, cost_usd=0.5)
    assert store.month_cost() == pytest.approx(0.51)


def test_top_phrases_and_day_totals(store):
    for _ in range(3):
        store.add_interaction(utterance="Luz do pendente")
    store.add_interaction(utterance="outra frase")
    store.add_interaction(utterance="falhou", error="boom")
    top = store.top_phrases()
    assert top[0]["count"] == 3 and top[0]["phrase"] == "Luz do pendente" and len(top) == 2
    assert store.day_totals()["fallbacks"] == 4 and store.day_totals()["repeated"] == 2


# ---------- analysis: validation is deterministic ----------

ENTITIES = [
    {"id": "light.sala_pendente", "domain": "light", "name": "Sala Pendente", "area": "Sala",
     "aliases": [], "aliases_raw": [None], "device_class": None},
    {"id": "light.cozinha", "domain": "light", "name": "Cozinha", "area": "Cozinha",
     "aliases": [], "aliases_raw": [None], "device_class": None},
    {"id": "lock.porta", "domain": "lock", "name": "Porta", "area": None,
     "aliases": [], "aliases_raw": [None], "device_class": None},
]


def interactions():
    rows = []
    for i in range(3):
        rows.append({"ts": 100 + i, "utterance": "Acende o pendente da sala", "reply": "Pronto.", "error": None,
                     "tools": [{"name": "light__HassLightSet", "input": {"name": "Sala Pendente"}}]})
    rows.append({"ts": 200, "utterance": "Tranca a porta", "reply": "ok", "error": None, "tools": []})
    rows.append({"ts": 201, "utterance": "erro", "reply": "", "error": "x", "tools": []})
    return rows


def test_summarize_groups_and_skips_errors():
    phrases = summarize_phrases(interactions())
    assert [g["count"] for g in phrases] == [3, 1]
    assert "light__HassLightSet" in phrases[0]["tools"][0]


def test_validate_accepts_good_alias_and_rejects_bad_ones():
    phrases = summarize_phrases(interactions())
    entities = json.loads(json.dumps(ENTITIES))
    items = [
        {"kind": "alias", "phrase": "Acende o pendente da sala", "entity_id": "light.sala_pendente",
         "alias": "pendente da sala", "title": "Pendente"},
        {"kind": "alias", "phrase": "Acende o pendente da sala", "entity_id": "lock.porta",
         "alias": "pendente", "title": "lock"},                                  # unsafe domain
        {"kind": "alias", "phrase": "Acende o pendente da sala", "entity_id": "light.cozinha",
         "alias": "lustre", "title": "not in phrase"},                           # alias not said
        {"kind": "alias", "phrase": "never said", "entity_id": "light.cozinha",
         "alias": "never", "title": "invented phrase"},
        {"kind": "alias", "phrase": "Acende o pendente da sala", "entity_id": "light.cozinha",
         "alias": "pendente da sala", "title": "duplicate"},                     # ambiguous after the first
        {"kind": "tip", "phrase": "Tranca a porta", "title": "Make a scene"},
    ]
    accepted, rejected = validate(items, phrases, entities)
    assert [a["kind"] for a in accepted] == ["alias", "tip"]
    assert accepted[0]["alias"] == "pendente da sala" and accepted[0]["evidence"] == 3
    assert accepted[0]["fingerprint"] == fingerprint("alias", "light.sala_pendente", "Pendente da  sala")
    assert len(rejected) == 4


class FakeMessages:
    def __init__(self, items):
        self.items = items
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        block = types.SimpleNamespace(type="tool_use", input={"suggestions": self.items})
        usage = types.SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0,
                                      cache_creation_input_tokens=0)
        return types.SimpleNamespace(content=[block], usage=usage)


@pytest.fixture
def fake_entities(monkeypatch):
    async def fetch(_settings):
        return json.loads(json.dumps(ENTITIES))
    monkeypatch.setattr(analysis, "fetch_entities", fetch)


async def test_analyzer_stores_validated_suggestions_and_records_cost(store, fake_entities):
    for _ in range(2):
        store.add_interaction(utterance="Acende o pendente da sala", reply="ok",
                              tools=[{"name": "light__HassLightSet", "input": {"name": "Sala Pendente"}}])
    items = [{"kind": "alias", "phrase": "Acende o pendente da sala", "entity_id": "light.sala_pendente",
              "alias": "pendente da sala", "title": "Pendente"}]
    client = types.SimpleNamespace(messages=FakeMessages(items))
    result = await Analyzer(Settings(), store, client).run()
    assert result["status"] == "ok" and result["created"] == 1
    assert store.list_suggestions("new")[0]["alias"] == "pendente da sala"
    assert store.last_analysis_run()["cost_usd"] > 0
    again = await Analyzer(Settings(), store, client).run()  # same proposal: nothing new
    assert again["created"] == 0


async def test_analyzer_without_data_does_not_call_the_model(store):
    client = types.SimpleNamespace(messages=FakeMessages([]))
    assert (await Analyzer(Settings(), store, client).run())["status"] == "nothing_to_analyze"
    assert client.messages.kwargs is None


async def test_analyzer_failure_is_recorded_not_raised(store, monkeypatch):
    store.add_interaction(utterance="x y")

    async def boom(_settings):
        raise RuntimeError("ha down")
    monkeypatch.setattr(analysis, "fetch_entities", boom)
    result = await Analyzer(Settings(), store, types.SimpleNamespace()).run()
    assert result["status"] == "error" and "ha down" in store.last_analysis_run()["error"]


def test_due_only_once_per_day_at_the_configured_hour(store):
    a = Analyzer(Settings(analysis_hour=4, timezone="UTC"), store, None)
    four = 1_700_000_000 - (1_700_000_000 % 86400) + 4 * 3600
    assert a.due(four) and not a.due(four + 3600 * 3)
    store.add_analysis_run(model="m", interactions=1, created=0, rejected=0, cost_usd=0, ts=four)
    assert not a.due(four + 60)
    assert not Analyzer(Settings(analysis_hour=-1), store, None).due(four)


# ---------- UI API and network rules ----------


def make_ui(tmp_path, ip="127.0.0.1", backend=None, analyzer=None, **kw):
    s = Settings(data_dir=tmp_path, **kw)
    st = Store(tmp_path / "u.sqlite3")
    app = create_app(s, backend or UnconfiguredBackend(s, "no key"), st, None, analyzer)
    transport = httpx.ASGITransport(app=app, client=(ip, 1))
    return httpx.AsyncClient(transport=transport, base_url="http://app"), st


async def test_ui_page_and_summary(tmp_path):
    client, st = make_ui(tmp_path)
    async with client:
        assert "Voice Assist Improver" in (await client.get("/ui/")).text
        data = (await client.get("/ui/api/summary")).json()
        assert data["status"]["configured"] is False and data["analysis"]["available"] is False
        assert (await client.post("/ui/api/analyze")).status_code == 409
    st.close()


async def test_ui_is_stricter_than_the_ollama_endpoint(tmp_path):
    client, st = make_ui(tmp_path, ip="10.1.2.3", allowed_networks=("10.0.0.0/8",))
    async with client:
        assert (await client.get("/api/version")).status_code == 200
        assert (await client.get("/ui/api/summary")).status_code == 403
    st.close()


async def test_unconfigured_backend_speaks_instead_of_failing(tmp_path):
    client, st = make_ui(tmp_path, language="pt-BR")
    async with client:
        r = await client.post("/api/chat", json={"model": "default", "stream": False,
                                                 "messages": [{"role": "user", "content": "oi"}]})
        assert "chave de API" in r.json()["message"]["content"]
    st.close()


async def test_suggestion_status_actions(tmp_path):
    client, st = make_ui(tmp_path)
    sid = st.add_suggestion(fingerprint="a", kind="tip", title="Tip", phrase="p", evidence=1)
    async with client:
        listed = (await client.get("/ui/api/suggestions")).json()["suggestions"]
        assert listed[0]["title"] == "Tip"
        assert (await client.post(f"/ui/api/suggestions/{sid}/status", json={"status": "never"})).status_code == 200
        assert (await client.post(f"/ui/api/suggestions/{sid}/status", json={"status": "x"})).status_code == 400
        assert (await client.post(f"/ui/api/suggestions/{sid}/apply")).status_code == 400  # tips are manual
        assert (await client.post("/ui/api/suggestions/999/status", json={"status": "done"})).status_code == 404
    assert st.get_suggestion(sid)["status"] == "never"
    st.close()
