"""Tests for ConflictDetector."""

from __future__ import annotations

import pytest
from src.core.conflict import ConflictDetector, BLOCK_THRESHOLD, WARN_THRESHOLD
from src.memory.schemas import (
    MemoryRecord,
    RecordType,
    RecordStatus,
    make_record_id,
)


def _make_intent(
    file_paths: list[str],
    text: str,
    project_id: str = "test-project",
    agent_id: str = "agent-x",
    status: str = RecordStatus.open.value,
) -> MemoryRecord:
    rid = make_record_id(RecordType.file_change_intent.value, project_id)
    return MemoryRecord(
        id=rid,
        record_type=RecordType.file_change_intent.value,
        project_id=project_id,
        workspace_id="shared",
        agent_id=agent_id,
        timestamp="2024-01-01T00:00:00+00:00",
        text=text,
        importance=3,
        status=status,
        payload={
            "file_paths": file_paths,
            "change_description": text,
            "task_id": "",
            "change_type": "modify",
        },
    )


def test_no_conflict_different_files(mock_detector: ConflictDetector):
    new_intent = _make_intent(
        file_paths=["src/payments/stripe.py"],
        text="Implement Stripe payment integration",
        agent_id="agent-b",
    )
    result = mock_detector.detect(new_intent, existing_intents=[])
    assert result.risk_score == 0.0
    assert result.recommendation == "proceed"
    assert result.conflicting_records == []


def test_file_overlap_conflict(
    mock_detector: ConflictDetector,
    mock_store,
    mock_index,
):
    # Seed an existing intent touching session.py
    existing = _make_intent(
        file_paths=["src/auth/session.py"],
        text="Refactor session management",
        agent_id="agent-a",
    )
    mock_store.upsert(existing)
    mock_index.index_record(existing)

    # New intent also touches session.py
    new_intent = _make_intent(
        file_paths=["src/auth/session.py"],
        text="Optimize session database queries",
        agent_id="agent-b",
    )
    result = mock_detector.detect(new_intent)
    assert result.risk_score > 0.0
    assert result.channels["file_overlap"] > 0.0
    # File overlap should push into warn or block territory
    assert result.recommendation in ("warn", "block")


def test_semantic_overlap_conflict(mock_detector: ConflictDetector):
    existing = _make_intent(
        file_paths=["src/auth/login.py"],
        text="authentication login JWT token security refactor session",
        agent_id="agent-a",
    )
    new_intent = _make_intent(
        file_paths=["src/security/token.py"],
        text="authentication JWT token security improvement login session",
        agent_id="agent-b",
    )
    # Pass existing as explicit list so TF-IDF comparison happens
    result = mock_detector.detect(new_intent, existing_intents=[existing])
    assert result.channels["semantic_overlap"] > 0.0


def test_no_overlap_with_done_intent(
    mock_detector: ConflictDetector,
    mock_store,
    mock_index,
):
    """Done intents should not trigger file overlap."""
    done_intent = _make_intent(
        file_paths=["src/auth/session.py"],
        text="Completed session refactor",
        agent_id="agent-a",
        status=RecordStatus.done.value,
    )
    mock_store.upsert(done_intent)
    mock_index.index_record(done_intent)

    new_intent = _make_intent(
        file_paths=["src/auth/session.py"],
        text="New work on session",
        agent_id="agent-b",
    )
    result = mock_detector.detect(new_intent)
    # Done record should not contribute to file overlap
    assert result.channels["file_overlap"] == 0.0


def test_risk_score_thresholds(mock_detector: ConflictDetector):
    """Verify threshold logic is applied correctly."""
    from src.core.conflict import ConflictResult

    # Manufacture results at each threshold
    def _make_result(score: float) -> str:
        if score >= BLOCK_THRESHOLD:
            return "block"
        elif score >= WARN_THRESHOLD:
            return "warn"
        else:
            return "proceed"

    assert _make_result(0.8) == "block"
    assert _make_result(0.7) == "block"
    assert _make_result(0.65) == "warn"
    assert _make_result(0.4) == "warn"
    assert _make_result(0.39) == "proceed"
    assert _make_result(0.0) == "proceed"


def test_conflict_result_suggested_order(
    mock_detector: ConflictDetector,
    mock_store,
    mock_index,
):
    existing = _make_intent(
        file_paths=["src/shared_util.py"],
        text="Refactor shared utility functions",
        agent_id="agent-a",
    )
    mock_store.upsert(existing)
    mock_index.index_record(existing)

    new_intent = _make_intent(
        file_paths=["src/shared_util.py"],
        text="Update shared utility error handling",
        agent_id="agent-b",
    )
    result = mock_detector.detect(new_intent)
    if result.conflicting_records:
        assert new_intent.id in result.suggested_order
        assert existing.id in result.suggested_order
