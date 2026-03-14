"""Prize-track evaluation harness for memory-driven conflict reduction."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from backend.memory.conflict_context import ConflictCompensator, TaskDraft


def run_prize_track_benchmark() -> dict[str, Any]:
    """Runs baseline vs memory-aware compensation benchmark."""
    baseline_tasks = [
        TaskDraft(task_id="task-a", agent_id="coder-1", file_paths=["src/auth.py", "src/api.py"]),
        TaskDraft(task_id="task-b", agent_id="coder-2", file_paths=["src/auth.py", "src/ui.py"]),
        TaskDraft(task_id="task-c", agent_id="coder-3", file_paths=["src/billing.py"]),
    ]

    no_memory_records: list[dict[str, Any]] = []
    history_records = [
        {
            "metadata": {
                "stage": "coordination",
                "status": "blocked",
                "file_paths": ["src/auth.py"],
                "conflict_score": 0.8,
            }
        },
        {
            "metadata": {
                "stage": "merge",
                "status": "failed",
                "file_paths": ["src/api.py", "src/auth.py"],
                "conflict_score": 0.6,
            }
        },
    ]

    compensator = ConflictCompensator()
    baseline = compensator.compensate(tasks=baseline_tasks, context_records=no_memory_records)
    with_memory = compensator.compensate(tasks=baseline_tasks, context_records=history_records)

    baseline_overlaps = _count_overlaps(baseline.adjusted_tasks)
    with_memory_overlaps = _count_overlaps(with_memory.adjusted_tasks)
    overlap_reduction = max(0, baseline_overlaps - with_memory_overlaps)

    return {
        "scenario": "async-planning-conflict-reduction",
        "baseline": {
            "tasks": [asdict(task) for task in baseline.adjusted_tasks],
            "signals": [asdict(signal) for signal in baseline.conflict_signals],
            "overlap_count": baseline_overlaps,
            "summary": baseline.summary,
        },
        "with_memory": {
            "tasks": [asdict(task) for task in with_memory.adjusted_tasks],
            "signals": [asdict(signal) for signal in with_memory.conflict_signals],
            "overlap_count": with_memory_overlaps,
            "summary": with_memory.summary,
        },
        "metrics": {
            "overlap_reduction": overlap_reduction,
            "conflict_signal_delta": len(with_memory.conflict_signals) - len(baseline.conflict_signals),
            "memory_context_used": True,
        },
    }


def _count_overlaps(tasks: list[TaskDraft]) -> int:
    overlap_count = 0
    for left_idx in range(len(tasks)):
        for right_idx in range(left_idx + 1, len(tasks)):
            if set(tasks[left_idx].file_paths) & set(tasks[right_idx].file_paths):
                overlap_count += 1
    return overlap_count


if __name__ == "__main__":
    print(json.dumps(run_prize_track_benchmark(), indent=2))

