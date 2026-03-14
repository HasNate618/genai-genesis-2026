"""
Memory record schemas used throughout the SPM system.

All Moorcheh documents share the MemoryRecord base and are differentiated
by the ``record_type`` field.  The ``text`` field is what Moorcheh indexes
for semantic search; ``payload`` holds type-specific structured data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Record type constants ─────────────────────────────────────────────────────

RECORD_TYPE_TASK_CLAIM = "task_claim"
RECORD_TYPE_PLAN_STEP = "plan_step"
RECORD_TYPE_DECISION = "decision"
RECORD_TYPE_FILE_CHANGE_INTENT = "file_change_intent"
RECORD_TYPE_DEPENDENCY_EDGE = "dependency_edge"
RECORD_TYPE_CONFLICT_ALERT = "conflict_alert"
RECORD_TYPE_MERGE_EVENT = "merge_event"
RECORD_TYPE_SUMMARY = "summary"

# ── Status constants ──────────────────────────────────────────────────────────

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_BLOCKED = "blocked"
STATUS_SUPERSEDED = "superseded"

# ── Importance scale ──────────────────────────────────────────────────────────
# 1 = trivial, 5 = critical (never compacted)

IMPORTANCE_MIN = 1
IMPORTANCE_DECISION = 5  # decisions and conflict resolutions are never compacted


def _short_uuid() -> str:
    return str(uuid.uuid4())[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_record_id(record_type: str, project_id: str) -> str:
    """Generate a unique, sortable record ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{record_type}:{project_id}:{ts}:{_short_uuid()}"


# ── Base record ───────────────────────────────────────────────────────────────


@dataclass
class MemoryRecord:
    """
    Base memory document stored in Moorcheh.

    The ``text`` field is the natural-language summary used for semantic
    retrieval.  ``payload`` stores type-specific structured fields.
    """

    id: str
    record_type: str
    project_id: str
    workspace_id: str  # "shared" or a branch name
    agent_id: str
    timestamp: str
    text: str
    importance: int  # 1..5
    status: str
    payload: dict[str, Any] = field(default_factory=dict)

    # ── Convenience constructors ──────────────────────────────────────────────

    @classmethod
    def task_claim(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        agent_id: str,
        task_id: str,
        description: str,
        file_paths: list[str],
        priority: int = 3,
    ) -> "MemoryRecord":
        text = (
            f"Agent {agent_id} claimed task '{task_id}': {description}. "
            f"Files: {', '.join(file_paths)}"
        )
        return cls(
            id=make_record_id(RECORD_TYPE_TASK_CLAIM, project_id),
            record_type=RECORD_TYPE_TASK_CLAIM,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=text,
            importance=priority,
            status=STATUS_IN_PROGRESS,
            payload={
                "task_id": task_id,
                "description": description,
                "file_paths": file_paths,
                "priority": priority,
            },
        )

    @classmethod
    def plan_step(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        agent_id: str,
        task_id: str,
        step_index: int,
        step_description: str,
        depends_on: list[str] | None = None,
    ) -> "MemoryRecord":
        text = (
            f"Plan step {step_index} for task '{task_id}' by agent {agent_id}: "
            f"{step_description}"
        )
        return cls(
            id=make_record_id(RECORD_TYPE_PLAN_STEP, project_id),
            record_type=RECORD_TYPE_PLAN_STEP,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=text,
            importance=2,
            status=STATUS_OPEN,
            payload={
                "task_id": task_id,
                "step_index": step_index,
                "step_description": step_description,
                "depends_on": depends_on or [],
            },
        )

    @classmethod
    def decision(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        agent_id: str,
        decision_text: str,
        rationale: str,
        affected_files: list[str] | None = None,
    ) -> "MemoryRecord":
        text = f"Decision by {agent_id}: {decision_text}. Rationale: {rationale}"
        return cls(
            id=make_record_id(RECORD_TYPE_DECISION, project_id),
            record_type=RECORD_TYPE_DECISION,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=text,
            importance=IMPORTANCE_DECISION,
            status=STATUS_DONE,
            payload={
                "decision_text": decision_text,
                "rationale": rationale,
                "affected_files": affected_files or [],
            },
        )

    @classmethod
    def file_change_intent(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        agent_id: str,
        task_id: str,
        file_path: str,
        change_summary: str,
        change_type: str = "modify",  # create | modify | delete
    ) -> "MemoryRecord":
        text = (
            f"Agent {agent_id} intends to {change_type} '{file_path}' for task "
            f"'{task_id}': {change_summary}"
        )
        return cls(
            id=make_record_id(RECORD_TYPE_FILE_CHANGE_INTENT, project_id),
            record_type=RECORD_TYPE_FILE_CHANGE_INTENT,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=text,
            importance=3,
            status=STATUS_OPEN,
            payload={
                "task_id": task_id,
                "file_path": file_path,
                "change_summary": change_summary,
                "change_type": change_type,
            },
        )

    @classmethod
    def conflict_alert(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        agent_id: str,
        conflicting_record_ids: list[str],
        risk_score: float,
        recommendation: str,
        channel_scores: dict[str, float],
    ) -> "MemoryRecord":
        text = (
            f"Conflict alert (risk={risk_score:.2f}) for agent {agent_id}: "
            f"{recommendation}"
        )
        return cls(
            id=make_record_id(RECORD_TYPE_CONFLICT_ALERT, project_id),
            record_type=RECORD_TYPE_CONFLICT_ALERT,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=text,
            importance=IMPORTANCE_DECISION,
            status=STATUS_OPEN,
            payload={
                "conflicting_record_ids": conflicting_record_ids,
                "risk_score": risk_score,
                "recommendation": recommendation,
                "channel_scores": channel_scores,
            },
        )

    @classmethod
    def merge_event(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        agent_id: str,
        task_id: str,
        merged_files: list[str],
        merge_summary: str,
    ) -> "MemoryRecord":
        text = (
            f"Agent {agent_id} merged task '{task_id}' into workspace "
            f"'{workspace_id}'. Files: {', '.join(merged_files)}. {merge_summary}"
        )
        return cls(
            id=make_record_id(RECORD_TYPE_MERGE_EVENT, project_id),
            record_type=RECORD_TYPE_MERGE_EVENT,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            timestamp=_now_iso(),
            text=text,
            importance=4,
            status=STATUS_DONE,
            payload={
                "task_id": task_id,
                "merged_files": merged_files,
                "merge_summary": merge_summary,
            },
        )

    # ── Serialization helpers ─────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        import json

        return {
            "id": self.id,
            "record_type": self.record_type,
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "text": self.text,
            "importance": self.importance,
            "status": self.status,
            "payload": json.dumps(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        import json

        payload = data.get("payload", "{}")
        if isinstance(payload, str):
            payload = json.loads(payload)
        return cls(
            id=data["id"],
            record_type=data["record_type"],
            project_id=data["project_id"],
            workspace_id=data["workspace_id"],
            agent_id=data["agent_id"],
            timestamp=data["timestamp"],
            text=data["text"],
            importance=int(data["importance"]),
            status=data["status"],
            payload=payload,
        )
