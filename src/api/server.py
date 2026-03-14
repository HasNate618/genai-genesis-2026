"""
FastAPI server with all SPM routes.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.deps import (
    get_compactor,
    get_engine,
    get_index,
    get_metrics,
    get_store,
)
from src.api.models import (
    ClaimTaskRequest,
    ClaimTaskResponse,
    ExecutionOrderResponse,
    HealthResponse,
    MergeWorkspaceRequest,
    MergeWorkspaceResponse,
    QueryContextRequest,
    QueryContextResponse,
    RecordDecisionRequest,
    RecordDecisionResponse,
    RecordFileIntentRequest,
    RecordFileIntentResponse,
    RecordPlanStepRequest,
    RecordPlanStepResponse,
    TriggerCompactionRequest,
    TriggerCompactionResponse,
    UpdateTaskRequest,
    UpdateTaskResponse,
    ConflictAlertModel,
)
from src.core.compactor import CompactionWorker
from src.core.coordination import CoordinationEngine
from src.memory.index import SQLiteIndex
from src.memory.schemas import RecordType
from src.memory.store import MoorchehStore
from src.metrics.collector import MetricsCollector

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="SPM — Shared Agent Memory Layer",
    description="Multi-agent coordination API powered by Moorcheh semantic memory.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    start = time.perf_counter()
    request.state.correlation_id = correlation_id

    response: Response = await call_next(request)

    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Correlation-ID"] = correlation_id
    logger.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
        correlation_id=correlation_id,
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check(
    store: MoorchehStore = Depends(get_store),
    index: SQLiteIndex = Depends(get_index),
):
    store_health = store.health_check()
    index_stats = index.get_stats()
    overall = "ok" if store_health.get("status") == "ok" else "degraded"
    return HealthResponse(
        status=overall,
        store=store_health,
        index=index_stats,
    )


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@app.post("/claims", response_model=ClaimTaskResponse, tags=["claims"])
def claim_task(
    body: ClaimTaskRequest,
    engine: CoordinationEngine = Depends(get_engine),
    metrics: MetricsCollector = Depends(get_metrics),
):
    start = time.perf_counter()
    result = engine.claim_task(
        agent_id=body.agent_id,
        project_id=body.project_id,
        workspace_id=body.workspace_id,
        task_description=body.task_description,
        file_paths=body.file_paths,
        dependencies=body.dependencies,
    )
    metrics.record_operation("claim_task", (time.perf_counter() - start) * 1000)
    prevented = result["recommendation"] in ("block", "warn")
    metrics.record_conflict(prevented=prevented)
    return ClaimTaskResponse(**result)


@app.patch("/claims/{record_id}", response_model=UpdateTaskResponse, tags=["claims"])
def update_task_status(
    record_id: str,
    body: UpdateTaskRequest,
    engine: CoordinationEngine = Depends(get_engine),
    metrics: MetricsCollector = Depends(get_metrics),
):
    start = time.perf_counter()
    result = engine.update_task_status(
        record_id=record_id,
        new_status=body.new_status,
        agent_id=body.agent_id,
    )
    metrics.record_operation("update_task", (time.perf_counter() - start) * 1000)
    if not result.get("success") and result.get("error") == "record_not_found":
        raise HTTPException(status_code=404, detail="Record not found")
    return UpdateTaskResponse(
        success=result["success"],
        record_id=record_id,
        status=result.get("status", body.new_status),
        error=result.get("error"),
    )


@app.get("/claims/{project_id}", tags=["claims"])
def list_claims(
    project_id: str,
    store: MoorchehStore = Depends(get_store),
):
    records = store.list_records(
        filters={"project_id": project_id, "record_type": RecordType.task_claim.value}
    )
    return {
        "project_id": project_id,
        "claims": [
            {
                "record_id": r.id,
                "agent_id": r.agent_id,
                "status": r.status,
                "timestamp": r.timestamp,
                "task_description": r.payload.get("task_description", ""),
                "file_paths": r.payload.get("file_paths", []),
                "importance": r.importance,
            }
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Execution order
# ---------------------------------------------------------------------------

@app.get(
    "/execution-order/{project_id}/{workspace_id}",
    response_model=ExecutionOrderResponse,
    tags=["coordination"],
)
def get_execution_order(
    project_id: str,
    workspace_id: str,
    engine: CoordinationEngine = Depends(get_engine),
):
    order = engine.get_execution_order(project_id=project_id, workspace_id=workspace_id)
    return ExecutionOrderResponse(
        project_id=project_id, workspace_id=workspace_id, order=order
    )


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

@app.post("/decisions", response_model=RecordDecisionResponse, tags=["events"])
def record_decision(
    body: RecordDecisionRequest,
    engine: CoordinationEngine = Depends(get_engine),
    metrics: MetricsCollector = Depends(get_metrics),
):
    start = time.perf_counter()
    result = engine.record_decision(
        agent_id=body.agent_id,
        project_id=body.project_id,
        workspace_id=body.workspace_id,
        decision_text=body.decision_text,
        task_id=body.task_id,
        affected_files=body.affected_files,
    )
    metrics.record_operation("record_decision", (time.perf_counter() - start) * 1000)
    return RecordDecisionResponse(**result)


# ---------------------------------------------------------------------------
# Plan steps
# ---------------------------------------------------------------------------

@app.post("/plan-steps", response_model=RecordPlanStepResponse, tags=["events"])
def record_plan_step(
    body: RecordPlanStepRequest,
    engine: CoordinationEngine = Depends(get_engine),
    metrics: MetricsCollector = Depends(get_metrics),
):
    start = time.perf_counter()
    result = engine.record_plan_step(
        agent_id=body.agent_id,
        project_id=body.project_id,
        workspace_id=body.workspace_id,
        step_text=body.step_text,
        task_id=body.task_id,
        step_number=body.step_number,
        total_steps=body.total_steps,
    )
    metrics.record_operation("record_plan_step", (time.perf_counter() - start) * 1000)
    return RecordPlanStepResponse(**result)


# ---------------------------------------------------------------------------
# File intents
# ---------------------------------------------------------------------------

@app.post("/file-intents", response_model=RecordFileIntentResponse, tags=["events"])
def record_file_intent(
    body: RecordFileIntentRequest,
    engine: CoordinationEngine = Depends(get_engine),
    metrics: MetricsCollector = Depends(get_metrics),
):
    start = time.perf_counter()
    result = engine.record_file_intent(
        agent_id=body.agent_id,
        project_id=body.project_id,
        workspace_id=body.workspace_id,
        file_paths=body.file_paths,
        change_description=body.change_description,
        task_id=body.task_id,
        change_type=body.change_type,
    )
    metrics.record_operation("record_file_intent", (time.perf_counter() - start) * 1000)
    conflict_data = result.get("conflict", {})
    conflict_model = None
    if conflict_data:
        conflict_model = ConflictAlertModel(
            risk_score=conflict_data.get("risk_score", 0.0),
            channels=conflict_data.get("channels", {}),
            conflicting_record_ids=conflict_data.get("conflicting_records", []),
            recommendation=conflict_data.get("recommendation", "proceed"),
            suggested_order=conflict_data.get("suggested_order", []),
        )
    return RecordFileIntentResponse(
        record_id=result["record_id"],
        status=result["status"],
        conflict=conflict_model,
    )


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------

@app.get("/conflicts/{project_id}", tags=["coordination"])
def list_conflict_alerts(
    project_id: str,
    store: MoorchehStore = Depends(get_store),
):
    records = store.list_records(
        filters={"project_id": project_id, "record_type": RecordType.conflict_alert.value}
    )
    return {
        "project_id": project_id,
        "alerts": [
            {
                "record_id": r.id,
                "timestamp": r.timestamp,
                "risk_score": r.payload.get("risk_score", 0.0),
                "recommendation": r.payload.get("recommendation", "proceed"),
                "channels": r.payload.get("channels", {}),
                "text": r.text,
            }
            for r in sorted(records, key=lambda x: x.timestamp, reverse=True)
        ],
    }


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@app.post("/query", response_model=QueryContextResponse, tags=["retrieval"])
def query_context(
    body: QueryContextRequest,
    engine: CoordinationEngine = Depends(get_engine),
    metrics: MetricsCollector = Depends(get_metrics),
):
    start = time.perf_counter()
    result = engine.query_context(
        question=body.question,
        project_id=body.project_id,
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
    )
    metrics.record_operation("query_context", (time.perf_counter() - start) * 1000)
    metrics.record_grounding(result.get("grounded", False))
    return QueryContextResponse(**result)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

@app.post("/merge", response_model=MergeWorkspaceResponse, tags=["coordination"])
def merge_workspace(
    body: MergeWorkspaceRequest,
    engine: CoordinationEngine = Depends(get_engine),
    metrics: MetricsCollector = Depends(get_metrics),
):
    start = time.perf_counter()
    result = engine.merge_workspace(
        agent_id=body.agent_id,
        project_id=body.project_id,
        source_ws=body.source_workspace,
        target_ws=body.target_workspace,
        files_changed=body.files_changed,
    )
    metrics.record_operation("merge_workspace", (time.perf_counter() - start) * 1000)
    return MergeWorkspaceResponse(**result)


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------

@app.post("/compact", response_model=TriggerCompactionResponse, tags=["compaction"])
def trigger_compaction(
    body: TriggerCompactionRequest,
    compactor: CompactionWorker = Depends(get_compactor),
    metrics: MetricsCollector = Depends(get_metrics),
):
    result = compactor.compact(
        project_id=body.project_id,
        workspace_id=body.workspace_id,
    )
    metrics.record_compaction(result)
    return TriggerCompactionResponse(
        records_before=result.records_before,
        records_after=result.records_after,
        chars_before=result.chars_before,
        chars_after=result.chars_after,
        compression_ratio=result.compression_ratio,
        clusters_formed=result.clusters_formed,
        duration_seconds=result.duration_seconds,
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@app.get("/metrics", tags=["system"])
def get_metrics_summary(
    metrics: MetricsCollector = Depends(get_metrics),
    index: SQLiteIndex = Depends(get_index),
):
    summary = metrics.get_summary()
    histogram = metrics.get_latency_histogram()
    index_stats = index.get_stats()
    return {
        "metrics": summary,
        "latency_histogram": histogram,
        "index_stats": index_stats,
    }
