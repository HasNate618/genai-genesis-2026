"""Schema definitions for vectorized workflow context records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


SCHEMA_VERSION = "v1"


class RecordType(str, Enum):
    GOAL = "goal"
    PLAN = "plan"
    PLAN_REJECTION = "plan_rejection"
    APPROVAL = "approval"
    TASK = "task"
    AGENT_STATE = "agent_state"
    CONFLICT = "conflict"
    MERGE = "merge"
    QA = "qa"


class WorkflowStage(str, Enum):
    GOAL = "goal"
    PLANNING = "planning"
    COORDINATION = "coordination"
    CODING = "coding"
    MERGE = "merge"
    QA = "qa"


@dataclass(frozen=True)
class ContextRecord:
    """Canonical execution context event stored in Moorcheh vector namespace."""

    workflow_id: str
    run_id: str
    event_seq: int
    record_type: RecordType
    stage: WorkflowStage
    status: str
    raw_text: str
    agent_id: str = "system"
    task_id: str | None = None
    file_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    conflict_score: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workflow_id:
            raise ValueError("workflow_id is required")
        if not self.run_id:
            raise ValueError("run_id is required")
        if self.event_seq < 0:
            raise ValueError("event_seq must be >= 0")
        if not self.raw_text.strip():
            raise ValueError("raw_text cannot be empty")
        if not (0.0 <= self.conflict_score <= 1.0):
            raise ValueError("conflict_score must be between 0 and 1")

    @property
    def id(self) -> str:
        return build_record_id(
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            event_seq=self.event_seq,
            record_type=self.record_type.value,
        )

    @property
    def source(self) -> str:
        return f"wf:{self.workflow_id}:run:{self.run_id}"

    def to_vector_payload(
        self, *, vector: list[float], embedding_model: str, embedding_dimension: int
    ) -> dict[str, Any]:
        """Transforms the record into Moorcheh vector upload shape."""
        payload = {
            "id": self.id,
            "vector": vector,
            "source": self.source,
            "index": self.event_seq,
            "raw_text": self.raw_text,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "record_type": self.record_type.value,
            "stage": self.stage.value,
            "status": self.status,
            "task_id": self.task_id,
            "file_paths": self.file_paths,
            "depends_on": self.depends_on,
            "conflict_score": self.conflict_score,
            "timestamp": self.timestamp,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
            "schema_version": SCHEMA_VERSION,
        }
        payload.update(self.extra)
        return payload


def build_record_id(*, workflow_id: str, run_id: str, event_seq: int, record_type: str) -> str:
    """Generates deterministic IDs for idempotent writes."""
    return f"wf:{workflow_id}:run:{run_id}:evt:{event_seq}:{record_type}"

