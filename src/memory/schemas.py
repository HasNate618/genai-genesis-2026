from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import uuid


class RecordType(str, Enum):
    task_claim = "task_claim"
    plan_step = "plan_step"
    decision = "decision"
    file_change_intent = "file_change_intent"
    dependency_edge = "dependency_edge"
    conflict_alert = "conflict_alert"
    merge_event = "merge_event"
    summary = "summary"


class RecordStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    blocked = "blocked"
    superseded = "superseded"


def make_record_id(record_type: str, project_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{record_type}:{project_id}:{ts}:{short_uuid}"


@dataclass
class TaskClaimPayload:
    task_description: str = ""
    file_paths: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    task_id: str = ""


@dataclass
class PlanStepPayload:
    task_id: str = ""
    step_number: int = 0
    total_steps: int = 0
    step_text: str = ""
    completed: bool = False


@dataclass
class DecisionPayload:
    task_id: str = ""
    decision_text: str = ""
    affected_files: list = field(default_factory=list)
    rationale: str = ""


@dataclass
class FileChangeIntentPayload:
    task_id: str = ""
    file_paths: list = field(default_factory=list)
    change_description: str = ""
    change_type: str = "modify"  # create | modify | delete | rename


@dataclass
class DependencyEdgePayload:
    source_file: str = ""
    target_file: str = ""
    edge_type: str = "import"  # import | call | inherit | use


@dataclass
class ConflictAlertPayload:
    risk_score: float = 0.0
    channels: dict = field(default_factory=dict)
    conflicting_record_ids: list = field(default_factory=list)
    recommendation: str = "proceed"
    suggested_order: list = field(default_factory=list)
    new_intent_id: str = ""


@dataclass
class MergeEventPayload:
    source_workspace: str = ""
    target_workspace: str = ""
    files_changed: list = field(default_factory=list)
    conflicts_resolved: int = 0
    merge_commit: str = ""


@dataclass
class SummaryPayload:
    compressed_from_ids: list = field(default_factory=list)
    topic_tags: list = field(default_factory=list)
    task_ids: list = field(default_factory=list)
    original_record_count: int = 0
    chars_before: int = 0
    chars_after: int = 0


@dataclass
class MemoryRecord:
    id: str
    record_type: str
    project_id: str
    workspace_id: str
    agent_id: str
    timestamp: str
    text: str
    importance: int
    status: str
    payload: dict = field(default_factory=dict)
