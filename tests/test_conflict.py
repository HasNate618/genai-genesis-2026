"""
Tests for src/core/conflict.py
"""

from __future__ import annotations

import pytest

from src.core.conflict import ConflictDetector
from src.memory.index import SQLiteIndex
from src.memory.schemas import MemoryRecord, STATUS_IN_PROGRESS
from src.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_no_conflict_when_empty(detector: ConflictDetector) -> None:
    result = await detector.check(
        agent_id="agent-a",
        task_id="task-1",
        file_paths=["src/new_file.py"],
        intent_text="Create a brand new module",
    )
    assert result["action"] == "proceed"
    assert result["risk_score"] < 0.4


@pytest.mark.asyncio
async def test_file_overlap_triggers_conflict(
    detector: ConflictDetector, index: SQLiteIndex, store: MemoryStore
) -> None:
    # Agent B has an open intent on session.py
    existing_intent = MemoryRecord.file_change_intent(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-b",
        task_id="task-b",
        file_path="src/session.py",
        change_summary="Refactor session storage",
    )
    index.upsert(existing_intent)
    # Manually set status to in_progress
    index.update_status(existing_intent.id, STATUS_IN_PROGRESS)

    # Agent A now tries to claim the same file
    result = await detector.check(
        agent_id="agent-a",
        task_id="task-a",
        file_paths=["src/session.py"],
        intent_text="Modify session management logic",
    )
    # File overlap weight=0.5 => composite >= 0.5 => should be >= warn threshold
    assert result["action"] in ("warn", "block")
    assert result["channel_scores"]["file_overlap"] == 1.0


@pytest.mark.asyncio
async def test_same_agent_no_self_conflict(
    detector: ConflictDetector, index: SQLiteIndex
) -> None:
    # Agent A has an open intent
    intent = MemoryRecord.file_change_intent(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-a",
        task_id="task-a",
        file_path="src/auth.py",
        change_summary="Auth changes",
    )
    index.upsert(intent)
    index.update_status(intent.id, STATUS_IN_PROGRESS)

    # Same agent checks conflict with itself — should not block
    result = await detector.check(
        agent_id="agent-a",
        task_id="task-a2",
        file_paths=["src/auth.py"],
        intent_text="Continue auth changes",
    )
    # Self-conflict is excluded in file overlap check
    assert result["channel_scores"]["file_overlap"] == 0.0


@pytest.mark.asyncio
async def test_conflict_produces_alert_record(
    detector: ConflictDetector, index: SQLiteIndex, store: MemoryStore
) -> None:
    # Set up a file conflict
    intent = MemoryRecord.file_change_intent(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-b",
        task_id="task-b",
        file_path="src/conflict_file.py",
        change_summary="Change conflict file",
    )
    index.upsert(intent)
    index.update_status(intent.id, STATUS_IN_PROGRESS)

    result = await detector.check(
        agent_id="agent-a",
        task_id="task-a",
        file_paths=["src/conflict_file.py"],
        intent_text="Modify conflict file",
    )
    if result["action"] in ("warn", "block"):
        assert "alert_record_id" in result
        assert result["alert_record_id"] is not None
