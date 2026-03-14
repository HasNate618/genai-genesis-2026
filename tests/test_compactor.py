"""
Tests for src/core/compactor.py
"""

from __future__ import annotations

import json

import pytest

from src.core.compactor import Compactor, _rule_based_summarize
from src.memory.index import SQLiteIndex
from src.memory.schemas import MemoryRecord, STATUS_DONE
from src.memory.store import MemoryStore


def _make_done_record(project_id: str = "test-project", task_id: str = "t1", idx: int = 0) -> MemoryRecord:
    r = MemoryRecord.plan_step(
        project_id=project_id,
        workspace_id="test-ws",
        agent_id="agent-a",
        task_id=task_id,
        step_index=idx,
        step_description=f"Step {idx}: do something useful",
    )
    r.status = STATUS_DONE
    r.importance = 2  # eligible for compaction
    return r


@pytest.mark.asyncio
async def test_compaction_no_records(compactor: Compactor) -> None:
    result = await compactor.run()
    assert result["clusters_processed"] == 0
    assert result["docs_deleted"] == 0


@pytest.mark.asyncio
async def test_compaction_reduces_records(
    compactor: Compactor, index: SQLiteIndex, store: MemoryStore
) -> None:
    # Insert 5 compactable records for the same task
    for i in range(5):
        r = _make_done_record(idx=i)
        index.upsert(r)
        # Also store text in payload_json so extractor can read it
        # (the row is already upserted with payload_json by the index)

    count_before = index.count("test-project")
    result = await compactor.run()

    assert result["clusters_processed"] >= 1
    assert result["docs_deleted"] == 5
    # Summary replaces the 5 records, so net count = 1 summary
    count_after = index.count("test-project")
    assert count_after < count_before


@pytest.mark.asyncio
async def test_compaction_preserves_high_importance(
    compactor: Compactor, index: SQLiteIndex
) -> None:
    # Insert a high-importance decision — should NOT be compacted
    decision = MemoryRecord.decision(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-a",
        decision_text="Use microservices architecture",
        rationale="Scalability requirements",
    )
    index.upsert(decision)

    # Insert low-importance compactable records
    for i in range(3):
        r = _make_done_record(idx=i)
        index.upsert(r)

    result = await compactor.run()
    # Decision should still be present
    decision_row = index.get(decision.id)
    assert decision_row is not None


def test_rule_based_summarize_truncates() -> None:
    long_texts = ["word " * 200]
    summary = _rule_based_summarize(long_texts)
    assert len(summary) <= 600  # [Rule-based summary] prefix + 512 chars + truncation
    assert "[Rule-based summary]" in summary


@pytest.mark.asyncio
async def test_should_run_threshold(compactor: Compactor) -> None:
    result = await compactor.should_run()
    assert result is False
