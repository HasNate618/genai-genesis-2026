"""
Tests for src/core/coordination.py
"""

from __future__ import annotations

import pytest

from src.core.coordination import CoordinationEngine
from src.memory.index import SQLiteIndex
from src.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_claim_task_success(engine: CoordinationEngine) -> None:
    result = await engine.claim_task(
        agent_id="agent-a",
        task_id="task-1",
        description="Refactor auth module",
        file_paths=["src/auth.py"],
        priority=3,
    )
    assert result["status"] == "claimed"
    assert "record" in result
    assert result["record"] is not None


@pytest.mark.asyncio
async def test_claim_task_duplicate_is_queued(engine: CoordinationEngine) -> None:
    # First claim
    await engine.claim_task(
        agent_id="agent-a",
        task_id="task-dup",
        description="First claimer",
        file_paths=["src/dup.py"],
    )
    # Second claim for same task_id
    result = await engine.claim_task(
        agent_id="agent-b",
        task_id="task-dup",
        description="Second claimer",
        file_paths=["src/dup.py"],
    )
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_release_task(engine: CoordinationEngine) -> None:
    await engine.claim_task(
        agent_id="agent-a",
        task_id="task-rel",
        description="Release test",
        file_paths=["src/x.py"],
    )
    result = await engine.release_task(
        task_id="task-rel",
        agent_id="agent-a",
        merged_files=["src/x.py"],
        merge_summary="Done.",
    )
    assert result["status"] == "released"


def test_suggest_order_higher_priority_first(engine: CoordinationEngine, index: SQLiteIndex) -> None:
    # Pre-populate index with two task claims of different priority
    from src.memory.schemas import MemoryRecord

    rec_a = MemoryRecord.task_claim(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-a",
        task_id="high-prio",
        description="High priority task",
        file_paths=[],
        priority=5,
    )
    rec_b = MemoryRecord.task_claim(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-b",
        task_id="low-prio",
        description="Low priority task",
        file_paths=[],
        priority=1,
    )
    index.upsert(rec_a)
    index.upsert(rec_b)

    result = engine.suggest_order(
        agent_a="agent-a",
        task_a="high-prio",
        agent_b="agent-b",
        task_b="low-prio",
    )
    assert result["recommended_order"][0]["agent"] == "agent-a"


def test_get_queue_returns_list(engine: CoordinationEngine) -> None:
    queue = engine.get_queue(project_id="test-project")
    assert isinstance(queue, list)
