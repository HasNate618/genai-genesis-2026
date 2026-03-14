"""Diagnostics and memory endpoints for Moorcheh integration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.memory.context_writer import WorkflowContextWriter
from backend.memory.moorcheh_store import MoorchehVectorStore
from backend.memory.schemas import RecordType, WorkflowStage


router = APIRouter(prefix="/memory", tags=["memory"])
_store: MoorchehVectorStore | None = None
_writer: WorkflowContextWriter | None = None


def _get_store() -> MoorchehVectorStore:
    global _store
    if _store is None:
        _store = MoorchehVectorStore()
    return _store


def _get_writer() -> WorkflowContextWriter:
    global _writer
    if _writer is None:
        _writer = WorkflowContextWriter(_get_store())
    return _writer


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=100)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata_filters: dict[str, Any] | None = None


class DebugWriteRequest(BaseModel):
    workflow_id: str
    run_id: str
    record_type: RecordType
    stage: WorkflowStage
    status: str
    raw_text: str = Field(..., min_length=1)
    event_seq: int | None = None
    agent_id: str = "system"
    task_id: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    conflict_score: float = Field(default=0.0, ge=0.0, le=1.0)
    extra: dict[str, Any] = Field(default_factory=dict)


@router.post("/provision")
async def provision_namespace() -> dict[str, Any]:
    try:
        return _get_store().provision_namespace()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to provision namespace: {exc}") from exc


@router.get("/health")
async def health() -> dict[str, Any]:
    try:
        return _get_store().health_check()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Health check failed: {exc}") from exc


@router.get("/config")
async def config() -> dict[str, Any]:
    return get_settings().redacted()


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    return _get_store().telemetry.snapshot()


@router.post("/search")
async def search_context(payload: SearchRequest) -> dict[str, Any]:
    try:
        records = _get_store().search_context(
            query_text=payload.query,
            top_k=payload.top_k,
            threshold=payload.threshold,
            metadata_filters=payload.metadata_filters,
        )
        return {"count": len(records), "records": records}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Context search failed: {exc}") from exc


@router.post("/write-debug")
async def write_debug(payload: DebugWriteRequest) -> dict[str, Any]:
    try:
        return _get_writer().write_event(
            workflow_id=payload.workflow_id,
            run_id=payload.run_id,
            record_type=payload.record_type,
            stage=payload.stage,
            status=payload.status,
            raw_text=payload.raw_text,
            agent_id=payload.agent_id,
            task_id=payload.task_id,
            file_paths=payload.file_paths,
            depends_on=payload.depends_on,
            conflict_score=payload.conflict_score,
            event_seq=payload.event_seq,
            extra=payload.extra,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Debug write failed: {exc}") from exc

