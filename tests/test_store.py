import time

from voice_assist_improver.store import Store

DAY = 86400


def make(tmp_path):
    return Store(tmp_path / "s.sqlite3")


def test_add_and_read_back(tmp_path):
    store = make(tmp_path)
    store.add_interaction(utterance="turn on the light", reply="Done.", tools=[{"name": "x"}], latency_ms=5)
    rows = store.interactions_since(0)
    assert rows[0]["utterance"] == "turn on the light" and rows[0]["tools"] == [{"name": "x"}]


def test_purge_removes_only_old_rows(tmp_path):
    store = make(tmp_path)
    now = time.time()
    store.add_interaction(utterance="old", ts=now - 100 * DAY)
    store.add_interaction(utterance="new", ts=now - 1 * DAY)
    assert store.purge_older_than(90, now=now) == 1
    assert [r["utterance"] for r in store.interactions_since(0)] == ["new"]


def test_fallbacks_per_day_counts_repeats(tmp_path):
    store = make(tmp_path)
    now = time.time()
    # day -2: a, b ; day -1: a (repeat), c ; today: a (repeat), a (repeat)
    for offset, phrase in [(-2, "Lights on"), (-2, "dim it"), (-1, "lights ON!"), (-1, "open the blinds"), (0, "lights on"), (0, "Lights on")]:
        store.add_interaction(utterance=phrase, ts=now + offset * DAY - 60)
    store.add_interaction(utterance="boom", error="x", ts=now - 60)  # failures are not fallbacks that were served
    days = store.fallbacks_per_day(days=5, now=now)
    assert [(d["total"], d["repeated"]) for d in days] == [(2, 0), (2, 1), (2, 2)]


def test_empty_store_has_no_days(tmp_path):
    assert make(tmp_path).fallbacks_per_day() == []
