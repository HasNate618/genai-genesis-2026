"""Tests for CompactionWorker."""

from __future__ import annotations

import pytest
from src.core.compactor import CompactionWorker
from src.memory.schemas import (
    MemoryRecord,
    RecordType,
    RecordStatus,
    make_record_id,
)


PROJECT = "test-project"
WORKSPACE = "shared"


def _make_done_record(
    importance: int = 2,
    text: str = "Some completed task record",
    record_type: str = RecordType.plan_step.value,
    task_id: str = "task-001",
) -> MemoryRecord:
    rid = make_record_id(record_type, PROJECT)
    return MemoryRecord(
        id=rid,
        record_type=record_type,
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        agent_id="agent-a",
        timestamp="2024-01-01T00:00:00+00:00",
        text=text,
        importance=importance,
        status=RecordStatus.done.value,
        payload={"task_id": task_id},
    )


def test_compact_empty_project(mock_compactor: CompactionWorker):
    result = mock_compactor.compact(PROJECT, WORKSPACE)
    assert result.records_before == 0
    assert result.records_after == 0
    assert result.compression_ratio == 1.0
    assert result.clusters_formed == 0
    assert result.duration_seconds >= 0.0


def test_compact_reduces_record_count(
    mock_compactor: CompactionWorker,
    mock_store,
):
    # Seed 10 low-importance done records with verbose text so compression is real
    long_text = (
        "Implemented the feature module according to specification. "
        "Verified tests pass. Updated documentation and changelog. "
        "Reviewed with team and merged into main branch after approval. "
    )
    for i in range(10):
        r = _make_done_record(
            importance=2,
            text=f"Plan step {i}: {long_text}",
            task_id="task-001",
        )
        mock_store.upsert(r)

    result = mock_compactor.compact(PROJECT, WORKSPACE)
    assert result.records_before == 10
    assert result.records_after < result.records_before
    assert result.compression_ratio > 0.0
    assert result.clusters_formed >= 1


def test_high_importance_records_not_compacted(
    mock_compactor: CompactionWorker,
    mock_store,
):
    # High-importance records (importance=5) should NOT be compacted
    for i in range(5):
        r = _make_done_record(
            importance=5,
            text=f"Critical decision {i}: architecture choice",
            task_id="task-critical",
        )
        mock_store.upsert(r)

    # Low-importance records that should be compacted
    for i in range(3):
        r = _make_done_record(
            importance=2,
            text=f"Minor plan step {i}",
            task_id="task-minor",
        )
        mock_store.upsert(r)

    result = mock_compactor.compact(PROJECT, WORKSPACE)
    # Only the 3 low-importance records should be compacted
    assert result.records_before == 3
    # High-importance records remain untouched in store
    all_records = mock_store.list_records(filters={"project_id": PROJECT})
    high_importance = [r for r in all_records if r.importance == 5 and r.record_type != RecordType.summary.value]
    assert len(high_importance) == 5


def test_compression_ratio_reported(
    mock_compactor: CompactionWorker,
    mock_store,
):
    long_text = "This is a detailed plan step with lots of context about the implementation. " * 5
    for i in range(6):
        r = _make_done_record(
            importance=1,
            text=f"Task step {i}: {long_text}",
            task_id="task-verbose",
        )
        mock_store.upsert(r)

    result = mock_compactor.compact(PROJECT, WORKSPACE)
    assert result.chars_before > 0
    assert result.chars_after > 0
    assert result.compression_ratio > 0.0
    assert result.clusters_formed >= 1


def test_compact_idempotent(mock_compactor: CompactionWorker, mock_store):
    """Re-running compaction on an already-compacted project is a no-op."""
    for i in range(5):
        r = _make_done_record(importance=2, text=f"Step {i}", task_id="task-x")
        mock_store.upsert(r)

    result1 = mock_compactor.compact(PROJECT, WORKSPACE)
    assert result1.records_before == 5

    # Second run: summaries have importance=5 and are excluded
    result2 = mock_compactor.compact(PROJECT, WORKSPACE)
    assert result2.records_before == 0


def test_compact_open_records_not_touched(
    mock_compactor: CompactionWorker,
    mock_store,
):
    """Open (not done) records should never be compacted."""
    r = MemoryRecord(
        id=make_record_id(RecordType.task_claim.value, PROJECT),
        record_type=RecordType.task_claim.value,
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        agent_id="agent-a",
        timestamp="2024-01-01T00:00:00+00:00",
        text="Active task claim",
        importance=2,
        status=RecordStatus.open.value,
        payload={"task_id": "task-open"},
    )
    mock_store.upsert(r)

    result = mock_compactor.compact(PROJECT, WORKSPACE)
    assert result.records_before == 0

    remaining = mock_store.get(r.id)
    assert remaining is not None
    assert remaining.status == RecordStatus.open.value
