"""
Tests for src/memory/store.py
"""

from __future__ import annotations

import pytest

from src.memory.schemas import MemoryRecord
from src.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_upsert_and_get(store: MemoryStore) -> None:
    record = MemoryRecord.task_claim(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-1",
        task_id="task-a",
        description="Test task",
        file_paths=["src/foo.py"],
    )
    await store.upsert(record)
    doc = await store.get(record.id)
    assert doc is not None
    assert doc["id"] == record.id


@pytest.mark.asyncio
async def test_delete(store: MemoryStore) -> None:
    record = MemoryRecord.decision(
        project_id="test-project",
        workspace_id="test-ws",
        agent_id="agent-1",
        decision_text="Use JWT",
        rationale="Scalability",
    )
    await store.upsert(record)
    await store.delete(record.id)
    doc = await store.get(record.id)
    assert doc is None


@pytest.mark.asyncio
async def test_search_returns_list(store: MemoryStore) -> None:
    # Mock search returns empty list by default — just verify no exception
    results = await store.search("session authentication", top_k=5)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_answer_returns_dict(store: MemoryStore) -> None:
    result = await store.answer("What is the auth plan?")
    assert "answer" in result
    assert "citations" in result


@pytest.mark.asyncio
async def test_fallback_upsert_when_unavailable(tmp_path) -> None:
    fallback_path = str(tmp_path / "fallback.json")
    s = MemoryStore(project_id="proj", workspace_id="ws")
    s._moorcheh_available = False
    s._initialised = True
    s._fallback._path = __import__("pathlib").Path(fallback_path)

    record = MemoryRecord.task_claim(
        project_id="proj",
        workspace_id="ws",
        agent_id="agent-x",
        task_id="t1",
        description="fallback task",
        file_paths=[],
    )
    await s.upsert(record)
    # Should not raise; fallback stores locally
    doc = await s.get(record.id)
    assert doc is not None


@pytest.mark.asyncio
async def test_health_check_returns_dict(store: MemoryStore) -> None:
    result = await store.health_check()
    assert isinstance(result, dict)
    assert "moorcheh_available" in result
