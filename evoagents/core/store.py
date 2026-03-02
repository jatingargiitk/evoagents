"""SQLite trace store for run history."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunRecord:
    run_id: str
    ts: float
    question: str
    trace_json: dict[str, Any]
    rule_score: float = 0.0
    rule_tags: list[str] = field(default_factory=list)
    final_score: float | None = None
    final_tags: list[str] = field(default_factory=list)
    config_hash: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    question    TEXT NOT NULL,
    config_hash TEXT,
    trace_json  TEXT NOT NULL,
    rule_score  REAL NOT NULL DEFAULT 0.0,
    rule_tags_json TEXT NOT NULL DEFAULT '[]',
    final_score REAL,
    final_tags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts);

CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    event_type  TEXT NOT NULL,
    skill_name  TEXT,
    data_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class TraceStore:
    """SQLite-backed store for pipeline run traces and events."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def save_run(self, record: RunRecord) -> str:
        self._conn.execute(
            """INSERT INTO runs
               (run_id, ts, question, config_hash, trace_json,
                rule_score, rule_tags_json, final_score, final_tags_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.run_id,
                record.ts,
                record.question,
                record.config_hash,
                json.dumps(record.trace_json),
                record.rule_score,
                json.dumps(record.rule_tags),
                record.final_score,
                json.dumps(record.final_tags),
            ),
        )
        self._conn.commit()
        return record.run_id

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_last_run(self) -> RunRecord | None:
        row = self._conn.execute(
            "SELECT * FROM runs ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_runs(self, limit: int = 20) -> list[RunRecord]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def query_by_tags(self, tags: list[str], limit: int = 50) -> list[RunRecord]:
        """Find runs whose rule_tags contain any of the given tags."""
        if not tags:
            return []
        conditions = " OR ".join(
            ["rule_tags_json LIKE ?" for _ in tags]
        )
        params = [f"%{tag}%" for tag in tags]
        params.append(str(limit))  # type: ignore[arg-type]
        rows = self._conn.execute(
            f"SELECT * FROM runs WHERE {conditions} ORDER BY ts DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def query_by_skill_and_tags(
        self, skill: str, tags: list[str], limit: int = 50
    ) -> list[RunRecord]:
        """Find runs where a specific skill step produced specific failure tags."""
        if not tags:
            return self.list_runs(limit)
        conditions = " OR ".join(
            ["rule_tags_json LIKE ?" for _ in tags]
        )
        params = [f"%{tag}%" for tag in tags]
        params.append(f"%{skill}%")
        params.append(str(limit))  # type: ignore[arg-type]
        rows = self._conn.execute(
            f"""SELECT * FROM runs
                WHERE ({conditions})
                  AND trace_json LIKE ?
                ORDER BY ts DESC LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_runs_since(self, hours: float, limit: int = 100) -> list[RunRecord]:
        cutoff = time.time() - (hours * 3600)
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def log_event(
        self, event_type: str, skill_name: str | None = None, data: dict | None = None
    ) -> str:
        eid = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO events (event_id, ts, event_type, skill_name, data_json) "
            "VALUES (?,?,?,?,?)",
            (eid, time.time(), event_type, skill_name, json.dumps(data or {})),
        )
        self._conn.commit()
        return eid

    def get_events(self, event_type: str | None = None, limit: int = 50) -> list[dict]:
        if event_type:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE event_type = ? ORDER BY ts DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_runs(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()
        return row[0] if row else 0

    def avg_score(self, skill: str | None = None) -> float | None:
        if skill:
            row = self._conn.execute(
                "SELECT AVG(rule_score) FROM runs WHERE trace_json LIKE ?",
                (f"%{skill}%",),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT AVG(rule_score) FROM runs").fetchone()
        return row[0] if row and row[0] is not None else None

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            ts=row["ts"],
            question=row["question"],
            trace_json=json.loads(row["trace_json"]),
            rule_score=row["rule_score"],
            rule_tags=json.loads(row["rule_tags_json"]),
            final_score=row["final_score"],
            final_tags=json.loads(row["final_tags_json"]),
            config_hash=row["config_hash"],
        )

    @staticmethod
    def new_run_id() -> str:
        return str(uuid.uuid4())[:12]
