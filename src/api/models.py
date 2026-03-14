"""
Pydantic request/response models for the SPM FastAPI server.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Request models ────────────────────────────────────────────────────────────


class ClaimTaskRequest(BaseModel):
    agent_id: str = Field(..., description="Unique identifier for the requesting agent")
    task_id: str = Field(..., description="Logical task identifier")
    description: str = Field(..., description="Human-readable description of the task")
    file_paths: list[str] = Field(
        default_factory=list,
        description="File paths the agent intends to modify",
    )
    priority: int = Field(
        3, ge=1, le=5, description="Task priority (1=low, 5=critical)"
    )


class ReleaseTaskRequest(BaseModel):
    agent_id: str
    merged_files: list[str] = Field(default_factory=list)
    merge_summary: str = ""


class IntentRequest(BaseModel):
    agent_id: str
    task_id: str
    file_path: str
    change_summary: str
    change_type: str = Field(
        "modify", description="create | modify | delete"
    )


class DecisionRequest(BaseModel):
    agent_id: str
    decision_text: str
    rationale: str
    affected_files: list[str] = Field(default_factory=list)


class ContextQueryRequest(BaseModel):
    question: str = Field(..., description="Natural-language question")
    agent_id: str = ""
    top_k: int = Field(5, ge=1, le=20)
    use_shared: bool = True


class ConflictCheckRequest(BaseModel):
    agent_id: str
    task_id: str
    file_paths: list[str]
    intent_text: str


class SuggestOrderRequest(BaseModel):
    agent_a: str
    task_a: str
    agent_b: str
    task_b: str


# ── Response models ───────────────────────────────────────────────────────────


class ClaimTaskResponse(BaseModel):
    status: str
    record: dict[str, Any] | None = None
    message: str


class ReleaseTaskResponse(BaseModel):
    status: str
    message: str


class ConflictCheckResponse(BaseModel):
    action: str  # proceed | warn | block
    risk_score: float
    channel_scores: dict[str, float]
    conflicting_ids: list[str]
    recommendation: str
    alert_record_id: str | None = None


class ContextQueryResponse(BaseModel):
    answer: str
    citations: list[str]
    retrieved_docs: list[dict[str, Any]]


class CompactionResponse(BaseModel):
    clusters_processed: int
    docs_deleted: int
    compression_ratio: float


class HealthResponse(BaseModel):
    status: str  # healthy | degraded
    moorcheh_available: bool
    sqlite_ok: bool
    details: dict[str, Any] = Field(default_factory=dict)


class SuggestOrderResponse(BaseModel):
    recommended_order: list[dict[str, str]]
    rationale: str


class MemoryStatsResponse(BaseModel):
    total_records: int
    moorcheh_available: bool
    namespace: str
    project_id: str
    workspace_id: str
