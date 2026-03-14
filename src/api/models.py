"""
Pydantic v2 API request/response models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    store: dict[str, Any] = Field(default_factory=dict)
    index: dict[str, Any] = Field(default_factory=dict)
    version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Conflict
# ---------------------------------------------------------------------------

class ConflictAlertModel(BaseModel):
    risk_score: float
    channels: dict[str, float] = Field(default_factory=dict)
    conflicting_record_ids: list[str] = Field(default_factory=list)
    recommendation: str
    suggested_order: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

class ClaimTaskRequest(BaseModel):
    agent_id: str
    project_id: str
    workspace_id: str = "shared"
    task_description: str
    file_paths: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ClaimTaskResponse(BaseModel):
    status: str  # claimed | blocked | queued
    record_id: str
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    risk_score: float = 0.0
    recommendation: str = "proceed"
    suggested_order: list[str] = Field(default_factory=list)


class UpdateTaskRequest(BaseModel):
    new_status: str
    agent_id: str


class UpdateTaskResponse(BaseModel):
    success: bool
    record_id: str
    status: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

class RecordDecisionRequest(BaseModel):
    agent_id: str
    project_id: str
    workspace_id: str = "shared"
    decision_text: str
    task_id: str
    affected_files: list[str] = Field(default_factory=list)


class RecordDecisionResponse(BaseModel):
    record_id: str
    status: str


# ---------------------------------------------------------------------------
# Plan steps
# ---------------------------------------------------------------------------

class RecordPlanStepRequest(BaseModel):
    agent_id: str
    project_id: str
    workspace_id: str = "shared"
    step_text: str
    task_id: str
    step_number: int = 1
    total_steps: int = 1


class RecordPlanStepResponse(BaseModel):
    record_id: str
    status: str


# ---------------------------------------------------------------------------
# File intents
# ---------------------------------------------------------------------------

class RecordFileIntentRequest(BaseModel):
    agent_id: str
    project_id: str
    workspace_id: str = "shared"
    file_paths: list[str]
    change_description: str
    task_id: str
    change_type: str = "modify"


class RecordFileIntentResponse(BaseModel):
    record_id: str
    status: str
    conflict: ConflictAlertModel | None = None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

class QueryContextRequest(BaseModel):
    question: str
    project_id: str
    workspace_id: str = "shared"
    agent_id: str = "user"


class QueryContextResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    grounded: bool = False


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

class MergeWorkspaceRequest(BaseModel):
    agent_id: str
    project_id: str
    source_workspace: str
    target_workspace: str
    files_changed: list[str] = Field(default_factory=list)


class MergeWorkspaceResponse(BaseModel):
    record_id: str
    status: str
    files_changed: list[str] = Field(default_factory=list)
    intents_superseded: int = 0


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------

class TriggerCompactionRequest(BaseModel):
    project_id: str
    workspace_id: str = "shared"


class TriggerCompactionResponse(BaseModel):
    records_before: int
    records_after: int
    chars_before: int
    chars_after: int
    compression_ratio: float
    clusters_formed: int
    duration_seconds: float


# ---------------------------------------------------------------------------
# Execution order
# ---------------------------------------------------------------------------

class ExecutionOrderResponse(BaseModel):
    project_id: str
    workspace_id: str
    order: list[dict[str, Any]] = Field(default_factory=list)
