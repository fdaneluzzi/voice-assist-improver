"""SQLite storage for interactions (what reached the LLM fallback) and the north-star metric.

Everything here is local to the user's machine. Interactions contain what people say at home, so the
store supports retention (`purge_older_than`).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .text import norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    client        TEXT,
    model         TEXT,
    backend       TEXT,
    utterance     TEXT    NOT NULL,
    reply         TEXT,
    tools         TEXT,
    latency_ms    INTEGER,
    first_text_ms INTEGER,
    error         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cache_read_tokens  INTEGER,
    cache_write_tokens INTEGER,
    cost_usd      REAL
);
CREATE INDEX IF NOT EXISTS idx_interactions_ts ON interactions(ts);
"""

# Columns added after the first version; added to databases created earlier.
MIGRATIONS = {
    "input_tokens": "INTEGER", "output_tokens": "INTEGER", "cache_read_tokens": "INTEGER",
    "cache_write_tokens": "INTEGER", "cost_usd": "REAL",
}


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            existing = {row["name"] for row in self._db.execute("PRAGMA table_info(interactions)")}
            for column, kind in MIGRATIONS.items():
                if column not in existing:
                    self._db.execute(f"ALTER TABLE interactions ADD COLUMN {column} {kind}")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add_interaction(
        self,
        *,
        utterance: str,
        reply: str = "",
        client: str = "",
        model: str = "",
        backend: str = "",
        tools: list[dict] | None = None,
        latency_ms: int | None = None,
        first_text_ms: int | None = None,
        error: str | None = None,
        ts: float | None = None,
        usage: dict | None = None,
    ) -> int:
        usage = usage or {}
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO interactions (ts, client, model, backend, utterance, reply, tools,"
                " latency_ms, first_text_ms, error, input_tokens, output_tokens, cache_read_tokens,"
                " cache_write_tokens, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts if ts is not None else time.time(), client, model, backend, utterance, reply,
                 json.dumps(tools or [], ensure_ascii=False), latency_ms, first_text_ms, error,
                 usage.get("input_tokens"), usage.get("output_tokens"), usage.get("cache_read_tokens"),
                 usage.get("cache_write_tokens"), usage.get("cost_usd")),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def interactions_since(self, since_ts: float) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM interactions WHERE ts >= ? ORDER BY ts", (since_ts,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tools"] = json.loads(d["tools"] or "[]")
            out.append(d)
        return out

    def cost_since(self, since_ts: float) -> float:
        with self._lock:
            row = self._db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM interactions WHERE ts >= ?", (since_ts,)
            ).fetchone()
        return float(row["total"])

    def month_cost(self, timezone: str = "UTC", now: float | None = None) -> float:
        """Estimated spend since the start of the current calendar month (in the given timezone)."""
        tz = ZoneInfo(timezone)
        moment = datetime.fromtimestamp(now if now is not None else time.time(), tz)
        start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.cost_since(start.timestamp())

    def purge_older_than(self, days: int, now: float | None = None) -> int:
        cutoff = (now if now is not None else time.time()) - days * 86400
        with self._lock:
            cur = self._db.execute("DELETE FROM interactions WHERE ts < ?", (cutoff,))
            self._db.commit()
            return cur.rowcount

    def fallbacks_per_day(
        self, days: int = 14, timezone: str = "UTC", now: float | None = None
    ) -> list[dict]:
        """The north-star metric: how many requests needed the LLM each day, and how many of those were
        a phrase already seen earlier in the window (the ones a shortcut could have handled locally).

        Returns one dict per day with activity: {"day": "YYYY-MM-DD", "total": n, "repeated": n}.
        """
        now = now if now is not None else time.time()
        tz = ZoneInfo(timezone)
        rows = self.interactions_since(now - days * 86400)
        seen: set[str] = set()
        per_day: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "repeated": 0})
        for r in rows:
            if r["error"]:
                continue
            day = datetime.fromtimestamp(r["ts"], tz).strftime("%Y-%m-%d")
            key = norm(r["utterance"])
            per_day[day]["total"] += 1
            if key in seen:
                per_day[day]["repeated"] += 1
            seen.add(key)
        return [{"day": d, **v} for d, v in sorted(per_day.items())]
