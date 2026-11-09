import sqlite3

from voice_assist_improver.store import Store


def chat(*messages):
    return {"model": "default:latest", "stream": False, "messages": [dict(m) for m in messages]}


async def test_export_has_history_tools_and_runs(make_client):
    client, store = make_client()
    async with client:
        await client.post("/api/chat", json=chat(
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "liga a luz"},
            {"role": "assistant", "content": "Pronto.", "tool_calls": [{"function": {"name": "x"}}]},
            {"role": "tool", "content": "ok"},
            {"role": "user", "content": "e a outra?"}))
        store.add_analysis_run(model="m", interactions=3, created=0, rejected=1, cost_usd=0.01,
                               rejections=["'x': needs 1 to 8 entities"])
        data = (await client.get("/ui/api/export")).json()
    row = data["interactions"][0]
    assert row["utterance"] == "e a outra?"
    # what the caller sent before this turn, system message and current turn left out
    assert [h["role"] for h in row["history"]] == ["user", "assistant", "tool"]
    assert row["history"][1]["tool_calls"] == 1 and "tool_calls" not in row["history"][0]
    assert data["analysis_runs"][0]["rejections"] == ["'x': needs 1 to 8 entities"]
    assert data["suggestions"] == []


async def test_export_limit_is_validated(make_client):
    client, _ = make_client()
    async with client:
        assert (await client.get("/ui/api/export?limit=0")).status_code == 422
        assert (await client.get("/ui/api/export?limit=5000")).status_code == 422


async def test_export_is_behind_the_ui_allow_list(make_client):
    client, _ = make_client(client_ip="10.0.0.7")  # allowed for Ollama, not for the UI
    async with client:
        assert (await client.get("/ui/api/export")).status_code == 403


def test_databases_from_before_the_new_columns_are_migrated(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, client TEXT,"
        " model TEXT, backend TEXT, utterance TEXT NOT NULL, reply TEXT, tools TEXT, latency_ms INTEGER,"
        " first_text_ms INTEGER, error TEXT);"
        "CREATE TABLE analysis_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, model TEXT,"
        " interactions INTEGER, created INTEGER, rejected INTEGER, cost_usd REAL, error TEXT);"
        "INSERT INTO interactions (ts, utterance, tools) VALUES (1, 'oi', '[]');"
        "INSERT INTO analysis_runs (ts, model) VALUES (1, 'm');")
    db.commit()
    db.close()
    store = Store(path)
    assert store.recent_interactions(5)[0]["history"] == []
    assert store.recent_analysis_runs(5)[0]["rejections"] == []
    store.close()
