"""
Coordination engine — task claiming, execution ordering, and merge protocols.

All state lives in Moorcheh (semantic) and SQLite (deterministic).  This
module is stateless: it reads/writes through MemoryStore + SQLiteIndex.

Key operations:
  - ``claim_task``    — atomically register a task claim for an agent
  - ``release_task``  — mark a task as done and unblock queued agents
  - ``get_queue``     — ordered list of tasks for a project/workspace
  - ``suggest_order`` — recommend execution order for two conflicting agents
"""

from __future__ import annotations

import logging
from typing import Any

from src.memory.index import SQLiteIndex
from src.memory.schemas import (
    MemoryRecord,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_OPEN,
    STATUS_BLOCKED,
)
from src.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class CoordinationEngine:
    """Orchestrates task claiming and execution ordering."""

    def __init__(self, store: MemoryStore, index: SQLiteIndex) -> None:
        self._store = store
        self._index = index

    # ── Task claiming ─────────────────────────────────────────────────────────

    async def claim_task(
        self,
        *,
        agent_id: str,
        task_id: str,
        description: str,
        file_paths: list[str],
        priority: int = 3,
    ) -> dict[str, Any]:
        """
        Register a task claim for an agent.

        Returns a dict with keys:
            ``status``  : "claimed" | "queued"
            ``record``  : serialised MemoryRecord
            ``message`` : human-readable explanation
        """
        # Check if this task_id is already claimed
        existing = self._index.find_by_task(task_id)
        active = [r for r in existing if r["status"] == STATUS_IN_PROGRESS]
        if active:
            return {
                "status": "queued",
                "record": None,
                "message": (
                    f"Task '{task_id}' is already in progress by agent "
                    f"'{active[0]['agent_id']}'. Your claim is queued."
                ),
            }

        record = MemoryRecord.task_claim(
            project_id=self._store.project_id,
            workspace_id=self._store.workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            description=description,
            file_paths=file_paths,
            priority=priority,
        )
        await self._store.upsert(record, use_shared=True)
        self._index.upsert(record)

        # Also register individual file-change intents for conflict detection
        for fp in file_paths:
            intent = MemoryRecord.file_change_intent(
                project_id=self._store.project_id,
                workspace_id=self._store.workspace_id,
                agent_id=agent_id,
                task_id=task_id,
                file_path=fp,
                change_summary=description,
            )
            await self._store.upsert(intent, use_shared=True)
            self._index.upsert(intent)

        logger.info(
            "Task claimed: task_id=%s agent=%s files=%s",
            task_id,
            agent_id,
            file_paths,
        )
        return {
            "status": "claimed",
            "record": record.to_dict(),
            "message": f"Task '{task_id}' claimed by agent '{agent_id}'.",
        }

    async def release_task(
        self,
        *,
        task_id: str,
        agent_id: str,
        merged_files: list[str],
        merge_summary: str,
    ) -> dict[str, Any]:
        """
        Mark a task as done and emit a merge event.

        Returns a dict with keys ``status`` and ``message``.
        """
        rows = self._index.find_by_task(task_id)
        for row in rows:
            self._index.update_status(row["id"], STATUS_DONE)

        merge = MemoryRecord.merge_event(
            project_id=self._store.project_id,
            workspace_id=self._store.workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            merged_files=merged_files,
            merge_summary=merge_summary,
        )
        await self._store.upsert(merge, use_shared=True)
        self._index.upsert(merge)

        logger.info("Task released: task_id=%s agent=%s", task_id, agent_id)
        return {
            "status": "released",
            "message": f"Task '{task_id}' completed and merged by agent '{agent_id}'.",
        }

    # ── Queue and ordering ────────────────────────────────────────────────────

    def get_queue(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """
        Return in-progress task claims ordered by priority (desc) then timestamp (asc).
        """
        rows = self._index.find_by_agent(
            agent_id="__all__", status=None
        )  # all agents
        # Broad query — fetch by project
        conn = self._index._conn  # direct access for this query
        pid = project_id or self._store.project_id
        raw = conn.execute(
            """
            SELECT * FROM records
            WHERE project_id = ?
              AND record_type = 'task_claim'
              AND status = 'in_progress'
            ORDER BY importance DESC, timestamp ASC
            """,
            (pid,),
        ).fetchall()
        return [dict(r) for r in raw]

    def suggest_order(
        self,
        agent_a: str,
        task_a: str,
        agent_b: str,
        task_b: str,
    ) -> dict[str, Any]:
        """
        Recommend execution order for two conflicting agents.

        Heuristic: the agent with the higher-priority (importance) task goes
        first.  Ties are broken by timestamp (earlier claim wins).
        """
        rows_a = self._index.find_by_task(task_a)
        rows_b = self._index.find_by_task(task_b)

        importance_a = max((r["importance"] for r in rows_a), default=3)
        importance_b = max((r["importance"] for r in rows_b), default=3)
        ts_a = min((r["timestamp"] for r in rows_a), default="")
        ts_b = min((r["timestamp"] for r in rows_b), default="")

        if importance_a > importance_b or (
            importance_a == importance_b and ts_a <= ts_b
        ):
            first, second = (agent_a, task_a), (agent_b, task_b)
        else:
            first, second = (agent_b, task_b), (agent_a, task_a)

        return {
            "recommended_order": [
                {"agent": first[0], "task": first[1]},
                {"agent": second[0], "task": second[1]},
            ],
            "rationale": (
                f"Agent '{first[0]}' has higher priority or earlier timestamp "
                f"and should proceed first."
            ),
        }
