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

CREATE TABLE IF NOT EXISTS suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT    NOT NULL UNIQUE,
    kind        TEXT    NOT NULL,
    entity_id   TEXT,
    alias       TEXT,
    phrase      TEXT,
    title       TEXT    NOT NULL,
    detail      TEXT,
    evidence    INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'new',
    verified    INTEGER NOT NULL DEFAULT 0,
    created     REAL    NOT NULL,
    updated     REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    model        TEXT,
    interactions INTEGER,
    created      INTEGER,
    rejected     INTEGER,
    cost_usd     REAL,
    error        TEXT
);
"""

# Suggestion lifecycle. "never" is the blocklist: such a suggestion is never created again.
STATUSES = ("new", "done", "dismissed", "never")
DISMISS_QUIET_DAYS = 30

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
        """Estimated spend since a moment: voice interactions plus the scheduled analysis."""
        with self._lock:
            row = self._db.execute(
                "SELECT COALESCE((SELECT SUM(cost_usd) FROM interactions WHERE ts >= :t), 0)"
                " + COALESCE((SELECT SUM(cost_usd) FROM analysis_runs WHERE ts >= :t), 0) AS total",
                {"t": since_ts}).fetchone()
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

    # ----- reading for the UI and the analysis -----

    def recent_interactions(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM interactions ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tools"] = json.loads(d["tools"] or "[]")
            out.append(d)
        return out

    def delete_interaction(self, interaction_id: int) -> bool:
        """Forget one recorded request (a test, or something the user does not want kept)."""
        with self._lock:
            cur = self._db.execute("DELETE FROM interactions WHERE id = ?", (interaction_id,))
            self._db.commit()
            return cur.rowcount > 0

    def top_phrases(self, days: int = 14, limit: int = 15, now: float | None = None) -> list[dict]:
        """Phrases that reached the LLM, most frequent first. `phrase` is the latest spelling seen."""
        now = now if now is not None else time.time()
        groups: dict[str, dict] = {}
        for r in self.interactions_since(now - days * 86400):
            if r["error"]:
                continue
            g = groups.setdefault(norm(r["utterance"]), {"phrase": "", "count": 0, "last": 0.0})
            g["count"] += 1
            if r["ts"] >= g["last"]:
                g["phrase"], g["last"] = r["utterance"], r["ts"]
        ranked = sorted(groups.values(), key=lambda g: (-g["count"], -g["last"]))
        return ranked[:limit]

    def day_totals(self, timezone: str = "UTC", now: float | None = None) -> dict:
        """Today's fallbacks (local day), how many repeated an earlier phrase, and the estimated cost."""
        now = now if now is not None else time.time()
        tz = ZoneInfo(timezone)
        start = datetime.fromtimestamp(now, tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today = start.strftime("%Y-%m-%d")
        daily = {d["day"]: d for d in self.fallbacks_per_day(days=30, timezone=timezone, now=now)}
        row = daily.get(today, {"total": 0, "repeated": 0})
        return {"fallbacks": row["total"], "repeated": row["repeated"],
                "cost_usd": self.cost_since(start.timestamp())}

    # ----- suggestions -----

    def add_suggestion(self, *, fingerprint: str, kind: str, title: str, detail: str = "",
                       entity_id: str | None = None, alias: str | None = None, phrase: str = "",
                       evidence: int = 0, now: float | None = None) -> int | None:
        """Store a new suggestion. Returns its id, or None when it must not be shown again: it already
        exists (new/done), was blocked ("never"), or was dismissed less than DISMISS_QUIET_DAYS ago."""
        now = now if now is not None else time.time()
        with self._lock:
            row = self._db.execute(
                "SELECT id, status, updated FROM suggestions WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if row is not None:
                quiet_until = row["updated"] + DISMISS_QUIET_DAYS * 86400
                if not (row["status"] == "dismissed" and now >= quiet_until):
                    return None
                self._db.execute(
                    "UPDATE suggestions SET status='new', title=?, detail=?, phrase=?, evidence=?, updated=?"
                    " WHERE id = ?", (title, detail, phrase, evidence, now, row["id"]))
                self._db.commit()
                return int(row["id"])
            cur = self._db.execute(
                "INSERT INTO suggestions (fingerprint, kind, entity_id, alias, phrase, title, detail,"
                " evidence, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (fingerprint, kind, entity_id, alias, phrase, title, detail, evidence, now, now))
            self._db.commit()
            return int(cur.lastrowid)

    def list_suggestions(self, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM suggestions"
        args: tuple = ()
        if status:
            query, args = query + " WHERE status = ?", (status,)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY evidence DESC, created DESC", args).fetchall()
        return [dict(r) for r in rows]

    def get_suggestion(self, suggestion_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return dict(row) if row else None

    def set_suggestion_status(self, suggestion_id: int, status: str, verified: bool = False,
                              now: float | None = None) -> bool:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        with self._lock:
            cur = self._db.execute(
                "UPDATE suggestions SET status = ?, verified = ?, updated = ? WHERE id = ?",
                (status, int(verified), now if now is not None else time.time(), suggestion_id))
            self._db.commit()
            return cur.rowcount > 0

    # ----- analysis runs -----

    def add_analysis_run(self, *, model: str, interactions: int, created: int, rejected: int,
                         cost_usd: float, error: str | None = None, ts: float | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO analysis_runs (ts, model, interactions, created, rejected, cost_usd, error)"
                " VALUES (?,?,?,?,?,?,?)",
                (ts if ts is not None else time.time(), model, interactions, created, rejected, cost_usd,
                 error))
            self._db.commit()
            return int(cur.lastrowid)

    def last_analysis_run(self) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM analysis_runs ORDER BY ts DESC LIMIT 1").fetchone()
        return dict(row) if row else None
