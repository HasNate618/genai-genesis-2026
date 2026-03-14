"""Contract for context passed to async agents before execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.memory.conflict_context import ConflictSignal, TaskDraft
from backend.memory.context_reader import ContextBundle


@dataclass(frozen=True)
class AsyncAgentContext:
    """Payload delivered to async agents at startup."""

    workflow_id: str
    run_id: str
    agent_id: str
    objective: str
    stage: str
    retrieved_query: str
    retrieved_summary: str
    retrieved_records: list[dict[str, Any]]
    assigned_tasks: list[dict[str, Any]]
    conflict_signals: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    schema_version: str = "v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_async_agent_context(
    *,
    workflow_id: str,
    run_id: str,
    agent_id: str,
    objective: str,
    stage: str,
    context_bundle: ContextBundle,
    assigned_tasks: list[TaskDraft],
    conflict_signals: list[ConflictSignal] | None = None,
    constraints: list[str] | None = None,
) -> AsyncAgentContext:
    """Builds a normalized payload for planner/coder/coordinator async agents."""
    return AsyncAgentContext(
        workflow_id=workflow_id,
        run_id=run_id,
        agent_id=agent_id,
        objective=objective,
        stage=stage,
        retrieved_query=context_bundle.query_text,
        retrieved_summary=context_bundle.summary,
        retrieved_records=context_bundle.records,
        assigned_tasks=[asdict(task) for task in assigned_tasks],
        conflict_signals=[asdict(signal) for signal in (conflict_signals or [])],
        constraints=constraints or [],
    )


def parse_async_agent_context(payload: dict[str, Any]) -> AsyncAgentContext:
    """Validates and parses payloads received by async agents."""
    required = [
        "workflow_id",
        "run_id",
        "agent_id",
        "objective",
        "stage",
        "retrieved_query",
        "retrieved_summary",
        "retrieved_records",
        "assigned_tasks",
    ]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Invalid async agent context payload. Missing: {', '.join(missing)}")
    return AsyncAgentContext(
        workflow_id=str(payload["workflow_id"]),
        run_id=str(payload["run_id"]),
        agent_id=str(payload["agent_id"]),
        objective=str(payload["objective"]),
        stage=str(payload["stage"]),
        retrieved_query=str(payload["retrieved_query"]),
        retrieved_summary=str(payload["retrieved_summary"]),
        retrieved_records=list(payload["retrieved_records"]),
        assigned_tasks=list(payload["assigned_tasks"]),
        conflict_signals=list(payload.get("conflict_signals", [])),
        constraints=list(payload.get("constraints", [])),
        schema_version=str(payload.get("schema_version", "v1")),
    )

