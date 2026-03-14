"""Read path for planner/coordinator context prefetch from Moorcheh."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.memory.moorcheh_store import MoorchehVectorStore


@dataclass(frozen=True)
class ContextBundle:
    """Context package consumed by async agents before planning/coordinating."""

    query_text: str
    records: list[dict[str, Any]]
    summary: str


class WorkflowContextReader:
    """Retrieves and formats relevant execution context for async agents."""

    def __init__(self, store: MoorchehVectorStore) -> None:
        self.store = store

    def fetch_for_planner(
        self,
        *,
        workflow_id: str,
        goal_text: str,
        planned_files: list[str] | None = None,
        top_k: int | None = None,
    ) -> ContextBundle:
        query = self._build_query(
            goal_text=goal_text,
            planned_files=planned_files or [],
            mode="planner",
        )
        records = self.store.search_context(
            query_text=query,
            top_k=top_k,
            metadata_filters={"workflow_id": workflow_id},
        )
        return ContextBundle(query_text=query, records=records, summary=self._summarize(records))

    def fetch_for_coordinator(
        self,
        *,
        workflow_id: str,
        objective: str,
        candidate_files: list[str],
        top_k: int | None = None,
    ) -> ContextBundle:
        query = self._build_query(
            goal_text=objective,
            planned_files=candidate_files,
            mode="coordinator",
        )
        records = self.store.search_context(
            query_text=query,
            top_k=top_k,
            metadata_filters={"workflow_id": workflow_id},
        )
        return ContextBundle(query_text=query, records=records, summary=self._summarize(records))

    def format_for_prompt(self, bundle: ContextBundle, *, max_records: int = 10) -> str:
        """Formats retrieved records into a compact prompt-friendly context block."""
        lines = [
            "Retrieved workflow context:",
            f"- Query: {bundle.query_text}",
            f"- Records: {len(bundle.records)}",
            f"- Summary: {bundle.summary}",
            "",
            "Top records:",
        ]
        for index, record in enumerate(bundle.records[:max_records], start=1):
            lines.append(self._format_record(index=index, record=record))
        return "\n".join(lines)

    def _build_query(self, *, goal_text: str, planned_files: list[str], mode: str) -> str:
        files_hint = ", ".join(sorted(set(planned_files))) if planned_files else "no target files yet"
        return (
            f"{mode} objective: {goal_text}. "
            f"Prioritize unresolved tasks, conflict history, approvals, and work touching: {files_hint}."
        )

    def _summarize(self, records: list[dict[str, Any]]) -> str:
        if not records:
            return "No prior context found."

        statuses: dict[str, int] = {}
        stages: dict[str, int] = {}
        for row in records:
            metadata = row.get("metadata", row)
            status = str(metadata.get("status", "unknown"))
            stage = str(metadata.get("stage", "unknown"))
            statuses[status] = statuses.get(status, 0) + 1
            stages[stage] = stages.get(stage, 0) + 1

        status_summary = ", ".join(f"{key}:{value}" for key, value in sorted(statuses.items()))
        stage_summary = ", ".join(f"{key}:{value}" for key, value in sorted(stages.items()))
        return f"status({status_summary}) stage({stage_summary})"

    def _format_record(self, *, index: int, record: dict[str, Any]) -> str:
        metadata = record.get("metadata", record)
        raw_text = metadata.get("raw_text") or metadata.get("text") or ""
        score = record.get("score", metadata.get("score", 0.0))
        label = record.get("label", metadata.get("label", ""))
        stage = metadata.get("stage", "unknown")
        status = metadata.get("status", "unknown")
        task_id = metadata.get("task_id", "-")
        return (
            f"{index}. [{label}] score={score:.4f} stage={stage} status={status} task={task_id} "
            f"text={str(raw_text)[:220]}"
        )

