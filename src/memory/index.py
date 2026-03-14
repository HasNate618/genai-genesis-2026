"""
SQLite deterministic index for fast exact lookups.

Moorcheh handles semantic similarity queries.  SQLite handles structured
filters such as:
  - file path → which agents have open intents on this file?
  - agent_id + status → what is this agent currently working on?
  - record_type + timestamp range → recent events for compaction

Schema lives in a single ``records`` table that mirrors the MemoryRecord
fields plus a ``payload_json`` column for structured access after retrieval.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from src.memory.schemas import MemoryRecord

logger = logging.getLogger(__name__)


class SQLiteIndex:
    """Lightweight deterministic index backed by a local SQLite database."""

    _DDL = """
    CREATE TABLE IF NOT EXISTS records (
        id              TEXT PRIMARY KEY,
        record_type     TEXT NOT NULL,
        project_id      TEXT NOT NULL,
        workspace_id    TEXT NOT NULL,
        agent_id        TEXT NOT NULL,
        timestamp       TEXT NOT NULL,
        importance      INTEGER NOT NULL,
        status          TEXT NOT NULL,
        payload_json    TEXT NOT NULL DEFAULT '{}',
        file_path       TEXT,          -- denormalized from payload for fast lookup
        task_id         TEXT           -- denormalized from payload for fast lookup
    );

    CREATE INDEX IF NOT EXISTS idx_file_path ON records (file_path, status);
    CREATE INDEX IF NOT EXISTS idx_agent_status ON records (agent_id, status);
    CREATE INDEX IF NOT EXISTS idx_type_ts ON records (record_type, timestamp);
    CREATE INDEX IF NOT EXISTS idx_project ON records (project_id, workspace_id);
    CREATE INDEX IF NOT EXISTS idx_task ON records (task_id);
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._DDL)
        self._conn.commit()
        logger.info("SQLiteIndex initialised at %s", db_path)

    # ── Write operations ──────────────────────────────────────────────────────

    def upsert(self, record: MemoryRecord) -> None:
        payload = record.payload or {}
        file_path = payload.get("file_path")
        task_id = payload.get("task_id")
        self._conn.execute(
            """
            INSERT INTO records
                (id, record_type, project_id, workspace_id, agent_id,
                 timestamp, importance, status, payload_json, file_path, task_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                status       = excluded.status,
                importance   = excluded.importance,
                payload_json = excluded.payload_json,
                file_path    = excluded.file_path,
                task_id      = excluded.task_id
            """,
            (
                record.id,
                record.record_type,
                record.project_id,
                record.workspace_id,
                record.agent_id,
                record.timestamp,
                record.importance,
                record.status,
                json.dumps(payload),
                file_path,
                task_id,
            ),
        )
        self._conn.commit()

    def delete(self, record_id: str) -> None:
        self._conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        self._conn.commit()

    def update_status(self, record_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE records SET status = ? WHERE id = ?", (status, record_id)
        )
        self._conn.commit()

    # ── Read operations ───────────────────────────────────────────────────────

    def get(self, record_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        return dict(row) if row else None

    def find_by_file_path(
        self, file_path: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE file_path = ? AND status = ?",
                (file_path, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE file_path = ?", (file_path,)
            ).fetchall()
        return [dict(r) for r in rows]

    def find_by_agent(
        self, agent_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE agent_id = ? AND status = ?",
                (agent_id, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE agent_id = ?", (agent_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def find_by_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM records WHERE task_id = ?", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def find_compactable(
        self, project_id: str, max_importance: int
    ) -> list[dict[str, Any]]:
        """Return done/superseded records with importance <= max_importance."""
        rows = self._conn.execute(
            """
            SELECT * FROM records
            WHERE project_id = ?
              AND importance <= ?
              AND status IN ('done', 'superseded')
            ORDER BY timestamp ASC
            """,
            (project_id, max_importance),
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self, project_id: str | None = None) -> int:
        if project_id:
            return self._conn.execute(
                "SELECT COUNT(*) FROM records WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def health_check(self) -> bool:
        try:
            self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._conn.close()
