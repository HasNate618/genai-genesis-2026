"""
FastAPI application — all HTTP endpoints for the SPM coordination service.

Endpoint overview
-----------------
POST /claims/{task_id}       — claim a task
DELETE /claims/{task_id}     — release a task (mark done)
POST /intents                — register a file-change intent
POST /decisions              — store an architectural decision
POST /conflicts/check        — run conflict detection
POST /conflicts/suggest-order — recommend execution order
POST /context/query          — ask a natural-language question
GET  /context/stats          — memory statistics
POST /compaction/run         — trigger compaction
GET  /health                 — health check
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.deps import (
    get_compactor,
    get_detector,
    get_engine,
    get_index,
    get_store,
)
from src.api.models import (
    ClaimTaskRequest,
    ClaimTaskResponse,
    CompactionResponse,
    ConflictCheckRequest,
    ConflictCheckResponse,
    ContextQueryRequest,
    ContextQueryResponse,
    DecisionRequest,
    HealthResponse,
    IntentRequest,
    MemoryStatsResponse,
    ReleaseTaskRequest,
    ReleaseTaskResponse,
    SuggestOrderRequest,
    SuggestOrderResponse,
)
from src.core.compactor import Compactor
from src.core.conflict import ConflictDetector
from src.core.coordination import CoordinationEngine
from src.memory.index import SQLiteIndex
from src.memory.schemas import MemoryRecord
from src.memory.store import MemoryStore
from src.metrics.collector import MetricsCollector

logger = structlog.get_logger(__name__)

# ── Application lifespan ──────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = get_store()
    await store.initialise()
    logger.info("SPM service started")
    yield
    logger.info("SPM service shutting down")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Shared Project Memory (SPM) API",
    description=(
        "Multi-agent coordination service backed by Moorcheh semantic memory. "
        "Provides task claiming, conflict detection, context querying, and "
        "memory compaction for AI coding agent workflows."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_metrics = MetricsCollector()


# ── Middleware: request latency ───────────────────────────────────────────────


@app.middleware("http")
async def record_latency(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _metrics.record_request(request.url.path, elapsed_ms)
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse, tags=["observability"])
async def health_check(
    store: MemoryStore = Depends(get_store),
    index: SQLiteIndex = Depends(get_index),
):
    moorcheh_health = await store.health_check()
    sqlite_ok = index.health_check()
    is_healthy = sqlite_ok  # Moorcheh degraded is acceptable (fallback)
    return HealthResponse(
        status="healthy" if is_healthy else "degraded",
        moorcheh_available=moorcheh_health.get("moorcheh_available", False),
        sqlite_ok=sqlite_ok,
        details=moorcheh_health,
    )


# ── Claims ────────────────────────────────────────────────────────────────────


@app.post(
    "/claims/{task_id}",
    response_model=ClaimTaskResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["coordination"],
)
async def claim_task(
    task_id: str,
    body: ClaimTaskRequest,
    engine: CoordinationEngine = Depends(get_engine),
    detector: ConflictDetector = Depends(get_detector),
):
    # Run conflict check before claiming
    if body.file_paths:
        conflict_result = await detector.check(
            agent_id=body.agent_id,
            task_id=task_id,
            file_paths=body.file_paths,
            intent_text=body.description,
        )
        _metrics.record_conflict_check(conflict_result["action"])
        if conflict_result["action"] == "block":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Task blocked due to conflict.",
                    "conflict": conflict_result,
                },
            )

    result = await engine.claim_task(
        agent_id=body.agent_id,
        task_id=task_id,
        description=body.description,
        file_paths=body.file_paths,
        priority=body.priority,
    )
    return ClaimTaskResponse(**result)


@app.delete("/claims/{task_id}", response_model=ReleaseTaskResponse, tags=["coordination"])
async def release_task(
    task_id: str,
    body: ReleaseTaskRequest,
    engine: CoordinationEngine = Depends(get_engine),
):
    result = await engine.release_task(
        task_id=task_id,
        agent_id=body.agent_id,
        merged_files=body.merged_files,
        merge_summary=body.merge_summary,
    )
    return ReleaseTaskResponse(**result)


# ── Intents ───────────────────────────────────────────────────────────────────


@app.post("/intents", status_code=status.HTTP_201_CREATED, tags=["coordination"])
async def register_intent(
    body: IntentRequest,
    store: MemoryStore = Depends(get_store),
    index: SQLiteIndex = Depends(get_index),
):
    record = MemoryRecord.file_change_intent(
        project_id=store.project_id,
        workspace_id=store.workspace_id,
        agent_id=body.agent_id,
        task_id=body.task_id,
        file_path=body.file_path,
        change_summary=body.change_summary,
        change_type=body.change_type,
    )
    await store.upsert(record, use_shared=True)
    index.upsert(record)
    return {"status": "created", "record_id": record.id}


# ── Decisions ─────────────────────────────────────────────────────────────────


@app.post("/decisions", status_code=status.HTTP_201_CREATED, tags=["memory"])
async def store_decision(
    body: DecisionRequest,
    store: MemoryStore = Depends(get_store),
    index: SQLiteIndex = Depends(get_index),
):
    record = MemoryRecord.decision(
        project_id=store.project_id,
        workspace_id=store.workspace_id,
        agent_id=body.agent_id,
        decision_text=body.decision_text,
        rationale=body.rationale,
        affected_files=body.affected_files,
    )
    await store.upsert(record, use_shared=True)
    index.upsert(record)
    return {"status": "created", "record_id": record.id}


# ── Conflict detection ────────────────────────────────────────────────────────


@app.post(
    "/conflicts/check",
    response_model=ConflictCheckResponse,
    tags=["conflict"],
)
async def check_conflict(
    body: ConflictCheckRequest,
    detector: ConflictDetector = Depends(get_detector),
):
    result = await detector.check(
        agent_id=body.agent_id,
        task_id=body.task_id,
        file_paths=body.file_paths,
        intent_text=body.intent_text,
    )
    _metrics.record_conflict_check(result["action"])
    return ConflictCheckResponse(**result)


@app.post(
    "/conflicts/suggest-order",
    response_model=SuggestOrderResponse,
    tags=["conflict"],
)
async def suggest_order(
    body: SuggestOrderRequest,
    engine: CoordinationEngine = Depends(get_engine),
):
    result = engine.suggest_order(
        agent_a=body.agent_a,
        task_a=body.task_a,
        agent_b=body.agent_b,
        task_b=body.task_b,
    )
    return SuggestOrderResponse(**result)


# ── Context query ─────────────────────────────────────────────────────────────


@app.post(
    "/context/query",
    response_model=ContextQueryResponse,
    tags=["memory"],
)
async def query_context(
    body: ContextQueryRequest,
    store: MemoryStore = Depends(get_store),
):
    start = time.perf_counter()
    answer_result = await store.answer(
        body.question,
        top_k=body.top_k,
        use_shared=body.use_shared,
    )
    retrieved = await store.search(
        body.question,
        top_k=body.top_k,
        use_shared=body.use_shared,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    _metrics.record_retrieval(latency_ms, len(retrieved))

    return ContextQueryResponse(
        answer=answer_result.get("answer", ""),
        citations=answer_result.get("citations", []),
        retrieved_docs=retrieved,
    )


@app.get(
    "/context/stats",
    response_model=MemoryStatsResponse,
    tags=["memory"],
)
async def memory_stats(
    store: MemoryStore = Depends(get_store),
    index: SQLiteIndex = Depends(get_index),
):
    return MemoryStatsResponse(
        total_records=index.count(store.project_id),
        moorcheh_available=store.is_available,
        namespace=store._namespace,
        project_id=store.project_id,
        workspace_id=store.workspace_id,
    )


# ── Compaction ────────────────────────────────────────────────────────────────


@app.post(
    "/compaction/run",
    response_model=CompactionResponse,
    tags=["memory"],
)
async def run_compaction(
    compactor: Compactor = Depends(get_compactor),
):
    result = await compactor.run()
    _metrics.record_compaction(result["compression_ratio"], result["docs_deleted"])
    return CompactionResponse(**result)


# ── Metrics ───────────────────────────────────────────────────────────────────


@app.get("/metrics", tags=["observability"])
async def get_metrics():
    return _metrics.summary()
