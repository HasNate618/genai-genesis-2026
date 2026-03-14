"""
SQLite deterministic index for fast structured lookups.

Dependency order: schemas -> index
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import structlog

from src.config import Settings, get_settings
from src.memory.schemas import MemoryRecord, RecordType

logger = structlog.get_logger(__name__)


class SQLiteIndex:
    def __init__(self, settings: Settings | None = None, db_path: str | None = None) -> None:
        self._settings = settings or get_settings()
        if db_path is not None:
            self._db_path = db_path
        else:
            self._db_path = str(self._settings.sqlite_path)

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def initialize(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                record_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                timestamp TEXT NOT NULL,
                file_paths_json TEXT NOT NULL DEFAULT '[]',
                task_id TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS file_intents (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                task_id TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dependency_edges (
                id TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                target_file TEXT NOT NULL,
                edge_type TEXT NOT NULL DEFAULT 'import',
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_claims_project ON claims (project_id, workspace_id);
            CREATE INDEX IF NOT EXISTS idx_claims_status ON claims (status);
            CREATE INDEX IF NOT EXISTS idx_file_intents_file ON file_intents (file_path);
            CREATE INDEX IF NOT EXISTS idx_file_intents_status ON file_intents (status);
            CREATE INDEX IF NOT EXISTS idx_dep_source ON dependency_edges (source_file);
            CREATE INDEX IF NOT EXISTS idx_dep_target ON dependency_edges (target_file);
            """
        )
        conn.commit()
        logger.info("sqlite_index.initialized", db_path=self._db_path)

    def index_record(self, record: MemoryRecord) -> None:
        conn = self._get_conn()
        if record.record_type in (RecordType.task_claim.value, RecordType.task_claim):
            payload = record.payload
            file_paths = payload.get("file_paths", [])
            task_id = payload.get("task_id", record.id)
            conn.execute(
                """
                INSERT OR REPLACE INTO claims
                    (id, agent_id, project_id, workspace_id, record_type, status, timestamp, file_paths_json, task_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.agent_id,
                    record.project_id,
                    record.workspace_id,
                    record.record_type if isinstance(record.record_type, str) else record.record_type.value,
                    record.status if isinstance(record.status, str) else record.status.value,
                    record.timestamp,
                    json.dumps(file_paths),
                    task_id,
                ),
            )

        elif record.record_type in (RecordType.file_change_intent.value, RecordType.file_change_intent):
            payload = record.payload
            for fp in payload.get("file_paths", []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO file_intents
                        (id, agent_id, file_path, status, task_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.agent_id,
                        fp,
                        record.status if isinstance(record.status, str) else record.status.value,
                        payload.get("task_id", ""),
                        record.timestamp,
                    ),
                )

        elif record.record_type in (RecordType.dependency_edge.value, RecordType.dependency_edge):
            payload = record.payload
            conn.execute(
                """
                INSERT OR REPLACE INTO dependency_edges
                    (id, source_file, target_file, edge_type, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    payload.get("source_file", ""),
                    payload.get("target_file", ""),
                    payload.get("edge_type", "import"),
                    record.timestamp,
                ),
            )

        conn.commit()
        logger.debug("sqlite_index.indexed", record_id=record.id, record_type=str(record.record_type))

    def find_claims_by_file(self, file_path: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM claims WHERE file_paths_json LIKE ?",
            (f"%{file_path}%",),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_active_intents_by_files(self, file_paths: list[str]) -> list[dict]:
        if not file_paths:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" * len(file_paths))
        rows = conn.execute(
            f"""
            SELECT * FROM file_intents
            WHERE file_path IN ({placeholders})
              AND status NOT IN ('done', 'superseded')
            """,
            file_paths,
        ).fetchall()
        return [dict(r) for r in rows]

    def find_dependency_overlap(self, file_paths: list[str]) -> list[dict]:
        if not file_paths:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" * len(file_paths))
        rows = conn.execute(
            f"""
            SELECT * FROM dependency_edges
            WHERE source_file IN ({placeholders})
               OR target_file IN ({placeholders})
            """,
            file_paths + file_paths,
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_done(self, record_id: str) -> None:
        conn = self._get_conn()
        conn.execute("UPDATE claims SET status = 'done' WHERE id = ?", (record_id,))
        conn.execute(
            "UPDATE file_intents SET status = 'done' WHERE id = ?", (record_id,)
        )
        conn.commit()

    def get_stats(self) -> dict[str, Any]:
        conn = self._get_conn()
        stats: dict[str, Any] = {}
        for table in ("claims", "file_intents", "dependency_edges"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            stats[f"{table}_count"] = row[0] if row else 0
        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM claims GROUP BY status"
        ).fetchall()
        stats["claims_by_status"] = {r[0]: r[1] for r in status_rows}
        return stats

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
