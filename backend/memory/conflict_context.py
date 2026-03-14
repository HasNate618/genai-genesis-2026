"""Conflict-aware task compensation based on retrieved workflow context."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from backend.config import Settings, get_settings


@dataclass(frozen=True)
class TaskDraft:
    """Task proposal produced before conflict compensation."""

    task_id: str
    agent_id: str
    file_paths: list[str]
    depends_on: list[str] = field(default_factory=list)
    priority: int = 50
    parallelizable: bool = True


@dataclass(frozen=True)
class ConflictSignal:
    """Detected signal indicating potential conflict risk."""

    kind: str
    file_path: str
    score: float
    source_task_ids: list[str]
    reason: str


@dataclass(frozen=True)
class CompensationDecision:
    """Compensation output passed back to coordinator and persisted as context."""

    adjusted_tasks: list[TaskDraft]
    conflict_signals: list[ConflictSignal]
    summary: str


class ConflictCompensator:
    """Adjusts task parallelism/dependencies using retrieved memory context."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def compensate(
        self, *, tasks: list[TaskDraft], context_records: list[dict[str, Any]]
    ) -> CompensationDecision:
        if not tasks:
            return CompensationDecision(adjusted_tasks=[], conflict_signals=[], summary="No tasks.")

        hot_files = _collect_hot_files(context_records)
        adjusted = [replace(task) for task in tasks]
        signals: list[ConflictSignal] = []

        # Pairwise overlap analysis.
        for left_idx in range(len(adjusted)):
            for right_idx in range(left_idx + 1, len(adjusted)):
                left = adjusted[left_idx]
                right = adjusted[right_idx]
                overlap = sorted(set(left.file_paths) & set(right.file_paths))
                if not overlap:
                    continue

                base_score = min(1.0, len(overlap) / max(1, min(len(left.file_paths), len(right.file_paths))))
                hottest = max(hot_files.get(path, 0.0) for path in overlap)
                score = min(1.0, base_score + hottest)

                signals.append(
                    ConflictSignal(
                        kind="file_overlap",
                        file_path=overlap[0],
                        score=score,
                        source_task_ids=[left.task_id, right.task_id],
                        reason=f"Overlapping files: {', '.join(overlap[:3])}",
                    )
                )

                if score >= self.settings.conflict_threshold:
                    # Serialize risky tasks by dependency and reducing parallelization.
                    if left.task_id not in right.depends_on:
                        right.depends_on.append(left.task_id)
                    adjusted[right_idx] = replace(
                        right,
                        depends_on=sorted(set(right.depends_on)),
                        parallelizable=False,
                        priority=max(right.priority, left.priority + 1),
                    )

        # Penalize tasks touching known "hot" files from prior failures/conflicts.
        for idx, task in enumerate(adjusted):
            penalty = 0.0
            for file_path in task.file_paths:
                penalty = max(penalty, hot_files.get(file_path, 0.0))
            if penalty <= 0:
                continue
            adjusted[idx] = replace(
                task,
                priority=task.priority + int(penalty * 10),
                parallelizable=task.parallelizable and penalty < self.settings.conflict_threshold,
            )
            signals.append(
                ConflictSignal(
                    kind="hot_file_history",
                    file_path=max(task.file_paths, key=lambda p: hot_files.get(p, 0.0)),
                    score=penalty,
                    source_task_ids=[task.task_id],
                    reason="Historical conflict/blocked history on touched file(s)",
                )
            )

        summary = _build_summary(signals=signals, task_count=len(tasks))
        return CompensationDecision(
            adjusted_tasks=sorted(adjusted, key=lambda task: (task.priority, task.task_id)),
            conflict_signals=signals,
            summary=summary,
        )


def _collect_hot_files(records: list[dict[str, Any]]) -> dict[str, float]:
    """Extracts historical conflict pressure by file path."""
    hot_files: dict[str, float] = {}
    for row in records:
        metadata = row.get("metadata", row)
        stage = str(metadata.get("stage", ""))
        status = str(metadata.get("status", ""))
        file_paths = metadata.get("file_paths", []) or []
        conflict_score = float(metadata.get("conflict_score", 0.0) or 0.0)
        if stage in {"merge", "coordination"} or status in {"blocked", "failed"}:
            base = max(0.2, conflict_score)
            for file_path in file_paths:
                hot_files[file_path] = max(hot_files.get(file_path, 0.0), base)
    return hot_files


def _build_summary(*, signals: list[ConflictSignal], task_count: int) -> str:
    if not signals:
        return f"No conflict signals across {task_count} tasks."
    high = sum(1 for signal in signals if signal.score >= 0.7)
    medium = sum(1 for signal in signals if 0.4 <= signal.score < 0.7)
    low = len(signals) - high - medium
    return (
        f"Detected {len(signals)} conflict signals across {task_count} tasks "
        f"(high={high}, medium={medium}, low={low})."
    )

