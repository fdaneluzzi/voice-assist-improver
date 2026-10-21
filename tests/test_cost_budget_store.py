import sqlite3
import time
from types import SimpleNamespace as NS

import pytest

from voice_assist_improver.backends import Done, TextDelta
from voice_assist_improver.budget import Budget
from voice_assist_improver.cost import PRICES, Usage, cost_usd, usage_record
from voice_assist_improver.store import Store


def test_cost_for_known_and_unknown_models():
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
    p = PRICES["claude-sonnet-5-5"]
    assert cost_usd("claude-sonnet-5-5", u) == pytest.approx(p.input + p.output + p.cache_read + p.cache_write)
    assert cost_usd("some-future-model", u) == cost_usd("claude-sonnet-5-5", u)  # priced like the default
    assert usage_record("some-future-model", u)["price_known"] is False
    assert usage_record("claude-haiku-5-5", u)["price_known"] is True


def test_usage_accumulates_and_tolerates_missing_fields():
    u = Usage()
    u.add(NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=None, cache_creation_input_tokens=2))
    u.add(NS(input_tokens=1))
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens) == (11, 5, 0, 2)


def test_small_model_costs_far_less_than_the_default():
    u = Usage(input_tokens=10_000, output_tokens=150)
    assert cost_usd("claude-haiku-5-5", u) * 10 < cost_usd("claude-sonnet-5-5", u)


def test_store_records_usage_and_sums_the_month(tmp_path):
    store = Store(tmp_path / "s.sqlite3")
    now = time.time()
    store.add_interaction(utterance="a", usage={"input_tokens": 5, "cost_usd": 0.25}, ts=now)
    store.add_interaction(utterance="b", usage={"cost_usd": 0.5}, ts=now)
    store.add_interaction(utterance="old", usage={"cost_usd": 9.0}, ts=now - 400 * 86400)
    store.add_interaction(utterance="no usage")
    assert store.month_cost(now=now) == pytest.approx(0.75)
    assert store.interactions_since(now - 5)[0]["input_tokens"] == 5


def test_store_migrates_a_database_created_before_the_usage_columns(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, client TEXT,
        model TEXT, backend TEXT, utterance TEXT NOT NULL, reply TEXT, tools TEXT, latency_ms INTEGER,
        first_text_ms INTEGER, error TEXT); INSERT INTO interactions (ts, utterance) VALUES (1, 'kept');""")
    db.commit()
    db.close()
    store = Store(path)
    store.add_interaction(utterance="new", usage={"cost_usd": 1.0})
    assert [r["utterance"] for r in store.interactions_since(0)] == ["kept", "new"]
    assert store.cost_since(0) == 1.0


def test_budget_only_blocks_when_a_cap_is_set_and_reached(tmp_path):
    store = Store(tmp_path / "s.sqlite3")
    store.add_interaction(utterance="x", usage={"cost_usd": 2.0})
    assert Budget(store, 0).exceeded() is False  # 0 = no cap
    assert Budget(store, 5.0).exceeded() is False
    assert Budget(store, 2.0).exceeded() is True


class CountingBackend:
    name = "counting"

    def __init__(self):
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        yield TextDelta("hi")
        yield Done(usage={"model": "claude-sonnet-5-5", "input_tokens": 1, "cost_usd": 0.5})

    async def close(self):
        return None


BODY = {"model": "default", "messages": [{"role": "user", "content": "hello"}]}


async def test_cost_from_the_backend_is_recorded(make_client):
    client, store = make_client(CountingBackend())
    await client.post("/api/chat", json=BODY)
    rec = store.interactions_since(0)[0]
    assert rec["cost_usd"] == 0.5 and rec["input_tokens"] == 1 and rec["model"] == "claude-sonnet-5-5"


async def test_api_stops_calling_the_backend_when_the_budget_is_reached(make_client):
    backend = CountingBackend()
    client, store = make_client(backend, monthly_budget_usd=1.0)
    await client.post("/api/chat", json=BODY)  # spends 0.5, still under the cap
    assert backend.calls == 1
    store.add_interaction(utterance="earlier", usage={"cost_usd": 0.6})  # now at 1.1
    reply = await client.post("/api/chat", json=BODY)
    assert "monthly AI budget" in reply.text and backend.calls == 1  # the backend was not called again
    assert store.interactions_since(0)[-1]["error"] == "budget_exceeded"
