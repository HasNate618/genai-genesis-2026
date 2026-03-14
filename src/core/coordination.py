"""
Coordination engine — task claiming, execution ordering, context queries.

Dependency order: schemas -> store/index -> conflict -> coordination
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from src.config import Settings, get_settings
from src.memory.schemas import (
    MemoryRecord,
    RecordType,
    RecordStatus,
    make_record_id,
    TaskClaimPayload,
    DecisionPayload,
    PlanStepPayload,
    FileChangeIntentPayload,
    MergeEventPayload,
)
from src.memory.store import MoorchehStore
from src.memory.index import SQLiteIndex
from src.core.conflict import ConflictDetector

logger = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CoordinationEngine:
    def __init__(
        self,
        store: MoorchehStore,
        index: SQLiteIndex,
        settings: Settings | None = None,
    ) -> None:
        self._store = store
        self._index = index
        self._settings = settings or get_settings()
        self._detector = ConflictDetector(store=store, index=index)

    # ------------------------------------------------------------------
    # Task claiming
    # ------------------------------------------------------------------

    def claim_task(
        self,
        agent_id: str,
        project_id: str,
        workspace_id: str,
        task_description: str,
        file_paths: list[str],
        dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        record_id = make_record_id(RecordType.task_claim.value, project_id)
        payload = TaskClaimPayload(
            task_description=task_description,
            file_paths=file_paths,
            dependencies=dependencies or [],
            task_id=record_id,
        )
        record = MemoryRecord(
            id=record_id,
            record_type=RecordType.task_claim.value,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=f"Task claim by {agent_id}: {task_description}. Files: {', '.join(file_paths)}",
            importance=4,
            status=RecordStatus.open.value,
            payload={
                "task_description": payload.task_description,
                "file_paths": payload.file_paths,
                "dependencies": payload.dependencies,
                "task_id": payload.task_id,
            },
        )

        # Check for conflicts via file_change_intent path
        intent_record = MemoryRecord(
            id=record_id,
            record_type=RecordType.file_change_intent.value,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=record.timestamp,
            text=record.text,
            importance=record.importance,
            status=RecordStatus.open.value,
            payload={
                "file_paths": file_paths,
                "change_description": task_description,
                "task_id": record_id,
                "change_type": "modify",
            },
        )
        conflict_result = self._detector.detect(intent_record)

        if conflict_result.recommendation == "block":
            record.status = RecordStatus.blocked.value
            status_out = "blocked"
        elif conflict_result.recommendation == "warn":
            record.status = RecordStatus.open.value
            status_out = "queued"
        else:
            record.status = RecordStatus.open.value
            status_out = "claimed"

        self._store.upsert(record)
        self._index.index_record(record)

        logger.info(
            "coordination.claim_task",
            record_id=record_id,
            agent_id=agent_id,
            status=status_out,
            risk_score=conflict_result.risk_score,
        )

        return {
            "status": status_out,
            "record_id": record_id,
            "conflicts": [
                {"id": r.id, "agent_id": r.agent_id, "text": r.text}
                for r in conflict_result.conflicting_records
            ],
            "risk_score": conflict_result.risk_score,
            "recommendation": conflict_result.recommendation,
            "suggested_order": conflict_result.suggested_order,
        }

    def update_task_status(
        self, record_id: str, new_status: str, agent_id: str
    ) -> dict[str, Any]:
        record = self._store.get(record_id)
        if record is None:
            return {"success": False, "error": "record_not_found"}

        record.status = new_status
        self._store.upsert(record)
        if new_status == RecordStatus.done.value:
            self._index.mark_done(record_id)

        logger.info(
            "coordination.update_status",
            record_id=record_id,
            new_status=new_status,
            agent_id=agent_id,
        )
        return {"success": True, "record_id": record_id, "status": new_status}

    # ------------------------------------------------------------------
    # Execution ordering
    # ------------------------------------------------------------------

    def get_execution_order(
        self, project_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        records = self._store.list_records(
            filters={
                "project_id": project_id,
                "workspace_id": workspace_id,
                "record_type": RecordType.task_claim.value,
            }
        )
        active = [
            r
            for r in records
            if r.status not in (RecordStatus.done.value, RecordStatus.superseded.value)
        ]
        # Sort by importance (desc) then timestamp (asc)
        active.sort(key=lambda r: (-r.importance, r.timestamp))
        return [
            {
                "record_id": r.id,
                "agent_id": r.agent_id,
                "status": r.status,
                "importance": r.importance,
                "timestamp": r.timestamp,
                "task_description": r.payload.get("task_description", ""),
                "file_paths": r.payload.get("file_paths", []),
            }
            for r in active
        ]

    # ------------------------------------------------------------------
    # Recording events
    # ------------------------------------------------------------------

    def record_decision(
        self,
        agent_id: str,
        project_id: str,
        workspace_id: str,
        decision_text: str,
        task_id: str,
        affected_files: list[str] | None = None,
    ) -> dict[str, Any]:
        record_id = make_record_id(RecordType.decision.value, project_id)
        record = MemoryRecord(
            id=record_id,
            record_type=RecordType.decision.value,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=f"Decision by {agent_id} for task {task_id}: {decision_text}",
            importance=5,
            status=RecordStatus.open.value,
            payload={
                "task_id": task_id,
                "decision_text": decision_text,
                "affected_files": affected_files or [],
                "rationale": "",
            },
        )
        self._store.upsert(record)
        logger.info("coordination.record_decision", record_id=record_id, agent_id=agent_id)
        return {"record_id": record_id, "status": "recorded"}

    def record_plan_step(
        self,
        agent_id: str,
        project_id: str,
        workspace_id: str,
        step_text: str,
        task_id: str,
        step_number: int,
        total_steps: int,
    ) -> dict[str, Any]:
        record_id = make_record_id(RecordType.plan_step.value, project_id)
        record = MemoryRecord(
            id=record_id,
            record_type=RecordType.plan_step.value,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=f"Plan step {step_number}/{total_steps} by {agent_id} (task {task_id}): {step_text}",
            importance=3,
            status=RecordStatus.open.value,
            payload={
                "task_id": task_id,
                "step_number": step_number,
                "total_steps": total_steps,
                "step_text": step_text,
                "completed": False,
            },
        )
        self._store.upsert(record)
        logger.info(
            "coordination.record_plan_step",
            record_id=record_id,
            step=f"{step_number}/{total_steps}",
        )
        return {"record_id": record_id, "status": "recorded"}

    def record_file_intent(
        self,
        agent_id: str,
        project_id: str,
        workspace_id: str,
        file_paths: list[str],
        change_description: str,
        task_id: str,
        change_type: str = "modify",
    ) -> dict[str, Any]:
        record_id = make_record_id(RecordType.file_change_intent.value, project_id)
        record = MemoryRecord(
            id=record_id,
            record_type=RecordType.file_change_intent.value,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=f"File intent by {agent_id} ({change_type}): {change_description}. Files: {', '.join(file_paths)}",
            importance=3,
            status=RecordStatus.open.value,
            payload={
                "task_id": task_id,
                "file_paths": file_paths,
                "change_description": change_description,
                "change_type": change_type,
            },
        )

        conflict_result = self._detector.detect(record)

        self._store.upsert(record)
        self._index.index_record(record)

        logger.info(
            "coordination.record_file_intent",
            record_id=record_id,
            risk_score=conflict_result.risk_score,
        )
        return {
            "record_id": record_id,
            "status": "recorded",
            "conflict": {
                "risk_score": conflict_result.risk_score,
                "recommendation": conflict_result.recommendation,
                "conflicting_records": [r.id for r in conflict_result.conflicting_records],
                "suggested_order": conflict_result.suggested_order,
            },
        }

    # ------------------------------------------------------------------
    # Context query
    # ------------------------------------------------------------------

    def query_context(
        self,
        question: str,
        project_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        results = self._store.similarity_search(
            query=question,
            top_k=self._settings.top_k_search,
            filters={"project_id": project_id},
        )

        if not results:
            return {
                "answer": "No relevant memory records found.",
                "sources": [],
                "grounded": False,
            }

        context_parts = []
        sources = []
        for r in results:
            context_parts.append(f"[{r.id}] ({r.timestamp}) {r.text}")
            sources.append(
                {
                    "record_id": r.id,
                    "record_type": r.record_type,
                    "agent_id": r.agent_id,
                    "timestamp": r.timestamp,
                    "text": r.text[:200],
                }
            )

        context = "\n".join(context_parts)
        answer = _rule_based_answer(question, results, context)

        logger.info(
            "coordination.query_context",
            question=question[:80],
            sources_count=len(sources),
        )
        return {
            "answer": answer,
            "sources": sources,
            "grounded": len(sources) > 0,
        }

    # ------------------------------------------------------------------
    # Merge workspace
    # ------------------------------------------------------------------

    def merge_workspace(
        self,
        agent_id: str,
        project_id: str,
        source_ws: str,
        target_ws: str,
        files_changed: list[str],
    ) -> dict[str, Any]:
        record_id = make_record_id(RecordType.merge_event.value, project_id)
        record = MemoryRecord(
            id=record_id,
            record_type=RecordType.merge_event.value,
            project_id=project_id,
            workspace_id=target_ws,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=(
                f"Merge by {agent_id}: workspace {source_ws} -> {target_ws}. "
                f"Files: {', '.join(files_changed)}"
            ),
            importance=4,
            status=RecordStatus.done.value,
            payload={
                "source_workspace": source_ws,
                "target_workspace": target_ws,
                "files_changed": files_changed,
                "conflicts_resolved": 0,
                "merge_commit": "",
            },
        )
        self._store.upsert(record)

        # Mark open intents in source workspace as superseded
        intents = self._store.list_records(
            filters={
                "project_id": project_id,
                "workspace_id": source_ws,
                "record_type": RecordType.file_change_intent.value,
            }
        )
        for intent in intents:
            if intent.status == RecordStatus.open.value:
                intent.status = RecordStatus.superseded.value
                self._store.upsert(intent)

        logger.info(
            "coordination.merge_workspace",
            record_id=record_id,
            source=source_ws,
            target=target_ws,
        )
        return {
            "record_id": record_id,
            "status": "merged",
            "files_changed": files_changed,
            "intents_superseded": len(intents),
        }


def _rule_based_answer(
    question: str, records: list[MemoryRecord], context: str
) -> str:
    """Simple rule-based answer grounded in retrieved records."""
    if not records:
        return "No relevant information found in memory."

    most_recent = sorted(records, key=lambda r: r.timestamp, reverse=True)[0]
    agent_ids = list({r.agent_id for r in records})
    record_types = list({r.record_type for r in records})

    lines = [
        f"Based on {len(records)} memory record(s) from agents {', '.join(agent_ids)}:",
        "",
    ]
    for r in records[:3]:
        lines.append(f"• [{r.record_type}] {r.text[:150]}")
        lines.append(f"  → recorded by {r.agent_id} at {r.timestamp}")
        lines.append("")

    if len(records) > 3:
        lines.append(f"... and {len(records) - 3} more records.")

    return "\n".join(lines)
