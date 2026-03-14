"""Tests for MoorchehStore (fallback mode)."""

from __future__ import annotations

import pytest
from src.memory.schemas import MemoryRecord, RecordType, RecordStatus, make_record_id
from src.memory.store import MoorchehStore


def _make_record(
    project_id: str = "test-project",
    agent_id: str = "agent-a",
    record_type: str = RecordType.task_claim.value,
    status: str = RecordStatus.open.value,
    text: str = "Test record",
    importance: int = 3,
) -> MemoryRecord:
    rid = make_record_id(record_type, project_id)
    return MemoryRecord(
        id=rid,
        record_type=record_type,
        project_id=project_id,
        workspace_id="shared",
        agent_id=agent_id,
        timestamp="2024-01-01T00:00:00+00:00",
        text=text,
        importance=importance,
        status=status,
        payload={},
    )


def test_upsert_and_get(mock_store: MoorchehStore):
    record = _make_record(text="Auth refactor task claim")
    mock_store.upsert(record)

    fetched = mock_store.get(record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.text == record.text
    assert fetched.agent_id == record.agent_id


def test_delete(mock_store: MoorchehStore):
    record = _make_record(text="Record to delete")
    mock_store.upsert(record)

    assert mock_store.get(record.id) is not None
    result = mock_store.delete(record.id)
    assert result is True
    assert mock_store.get(record.id) is None


def test_delete_nonexistent_returns_false(mock_store: MoorchehStore):
    result = mock_store.delete("does-not-exist:proj:123:abc")
    assert result is False


def test_similarity_search_returns_relevant_results(mock_store: MoorchehStore):
    r1 = _make_record(text="authentication login session refactor security")
    r2 = _make_record(text="database query optimization indexing performance")
    r3 = _make_record(text="authentication JWT token renewal security update")
    for r in (r1, r2, r3):
        mock_store.upsert(r)

    results = mock_store.similarity_search(
        query="authentication security", top_k=2, filters={}
    )
    assert len(results) <= 2
    result_ids = {r.id for r in results}
    # auth-related records should score higher than DB record
    assert r1.id in result_ids or r3.id in result_ids


def test_list_records_with_filters(mock_store: MoorchehStore):
    r1 = _make_record(project_id="proj-a", agent_id="agent-1")
    r2 = _make_record(project_id="proj-a", agent_id="agent-2")
    r3 = _make_record(project_id="proj-b", agent_id="agent-1")
    for r in (r1, r2, r3):
        mock_store.upsert(r)

    results = mock_store.list_records(filters={"project_id": "proj-a"})
    assert len(results) == 2
    assert all(r.project_id == "proj-a" for r in results)


def test_list_records_no_filters(mock_store: MoorchehStore):
    for i in range(5):
        mock_store.upsert(_make_record(text=f"Record {i}"))

    results = mock_store.list_records(filters={})
    assert len(results) >= 5


def test_health_check(mock_store: MoorchehStore):
    health = mock_store.health_check()
    assert "status" in health
    assert health["status"] in ("ok", "degraded")
    assert "backend" in health


def test_upsert_updates_existing(mock_store: MoorchehStore):
    record = _make_record(text="Original text", status=RecordStatus.open.value)
    mock_store.upsert(record)

    record.status = RecordStatus.done.value
    record.text = "Updated text"
    mock_store.upsert(record)

    fetched = mock_store.get(record.id)
    assert fetched.status == RecordStatus.done.value
    assert fetched.text == "Updated text"
