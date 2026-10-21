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
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_interactions_ts ON interactions(ts);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

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
    ) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO interactions (ts, client, model, backend, utterance, reply, tools,"
                " latency_ms, first_text_ms, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts if ts is not None else time.time(), client, model, backend, utterance, reply,
                 json.dumps(tools or [], ensure_ascii=False), latency_ms, first_text_ms, error),
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
