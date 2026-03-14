"""Workflow hooks for writing execution context records into Moorcheh."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.memory.moorcheh_store import MoorchehVectorStore
from backend.memory.schemas import ContextRecord, RecordType, WorkflowStage


class WorkflowContextWriter:
    """Writes normalized workflow events to the Moorcheh vector namespace."""

    def __init__(self, store: MoorchehVectorStore) -> None:
        self.store = store
        self._sequence_by_run: dict[str, int] = defaultdict(int)

    def write_event(
        self,
        *,
        workflow_id: str,
        run_id: str,
        record_type: RecordType,
        stage: WorkflowStage,
        status: str,
        raw_text: str,
        agent_id: str = "system",
        task_id: str | None = None,
        file_paths: list[str] | None = None,
        depends_on: list[str] | None = None,
        conflict_score: float = 0.0,
        event_seq: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seq = event_seq if event_seq is not None else self._next_event_seq(run_id)
        record = ContextRecord(
            workflow_id=workflow_id,
            run_id=run_id,
            event_seq=seq,
            record_type=record_type,
            stage=stage,
            status=status,
            raw_text=raw_text,
            agent_id=agent_id,
            task_id=task_id,
            file_paths=file_paths or [],
            depends_on=depends_on or [],
            conflict_score=conflict_score,
            extra=extra or {},
        )
        return self.store.write_record(record)

    def write_goal(self, *, workflow_id: str, run_id: str, goal_text: str) -> dict[str, Any]:
        return self.write_event(
            workflow_id=workflow_id,
            run_id=run_id,
            record_type=RecordType.GOAL,
            stage=WorkflowStage.GOAL,
            status="done",
            raw_text=goal_text,
        )

    def write_plan(
        self,
        *,
        workflow_id: str,
        run_id: str,
        plan_summary: str,
        status: str = "in_progress",
        agent_id: str = "planner",
    ) -> dict[str, Any]:
        return self.write_event(
            workflow_id=workflow_id,
            run_id=run_id,
            record_type=RecordType.PLAN,
            stage=WorkflowStage.PLANNING,
            status=status,
            raw_text=plan_summary,
            agent_id=agent_id,
        )

    def write_task_update(
        self,
        *,
        workflow_id: str,
        run_id: str,
        task_id: str,
        summary: str,
        status: str,
        agent_id: str,
        file_paths: list[str],
        depends_on: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.write_event(
            workflow_id=workflow_id,
            run_id=run_id,
            record_type=RecordType.TASK,
            stage=WorkflowStage.CODING,
            status=status,
            raw_text=summary,
            task_id=task_id,
            agent_id=agent_id,
            file_paths=file_paths,
            depends_on=depends_on or [],
        )

    def write_conflict_assessment(
        self,
        *,
        workflow_id: str,
        run_id: str,
        summary: str,
        conflict_score: float,
        file_paths: list[str],
        status: str = "done",
    ) -> dict[str, Any]:
        return self.write_event(
            workflow_id=workflow_id,
            run_id=run_id,
            record_type=RecordType.CONFLICT,
            stage=WorkflowStage.COORDINATION,
            status=status,
            raw_text=summary,
            file_paths=file_paths,
            conflict_score=conflict_score,
            agent_id="conflict-analyzer",
        )

    def _next_event_seq(self, run_id: str) -> int:
        value = self._sequence_by_run[run_id]
        self._sequence_by_run[run_id] += 1
        return value

