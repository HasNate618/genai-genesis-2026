"""Tests for CoordinationEngine."""

from __future__ import annotations

import pytest
from src.core.coordination import CoordinationEngine
from src.memory.schemas import RecordStatus


PROJECT = "test-project"
WORKSPACE = "shared"


def test_claim_task_success(mock_engine: CoordinationEngine):
    result = mock_engine.claim_task(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        task_description="Implement user registration",
        file_paths=["src/register.py", "src/email.py"],
    )
    assert result["status"] in ("claimed", "queued", "blocked")
    assert result["record_id"]
    assert isinstance(result["conflicts"], list)
    assert isinstance(result["risk_score"], float)
    assert 0.0 <= result["risk_score"] <= 1.0


def test_claim_task_no_conflict_for_different_files(mock_engine: CoordinationEngine):
    # Agent A claims files A and B
    mock_engine.claim_task(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        task_description="Auth refactor",
        file_paths=["src/auth/login.py", "src/auth/session.py"],
    )
    # Agent B claims completely different files → no conflict
    result = mock_engine.claim_task(
        agent_id="agent-b",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        task_description="Payment processing",
        file_paths=["src/payments/stripe.py", "src/payments/invoice.py"],
    )
    assert result["status"] == "claimed"
    assert result["risk_score"] < 0.4


def test_claim_task_conflict_detected(mock_engine: CoordinationEngine):
    # Agent A records a file intent for session.py
    mock_engine.record_file_intent(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        file_paths=["src/auth/session.py"],
        change_description="Refactor session management with JWT",
        task_id="task-a-001",
    )
    # Agent B tries to claim the same file
    result = mock_engine.claim_task(
        agent_id="agent-b",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        task_description="Optimize session database queries",
        file_paths=["src/auth/session.py"],
    )
    # Should have detected a conflict
    assert result["risk_score"] > 0.0
    assert result["recommendation"] in ("warn", "block")


def test_update_task_status(mock_engine: CoordinationEngine):
    claim = mock_engine.claim_task(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        task_description="Some task",
        file_paths=["src/foo.py"],
    )
    record_id = claim["record_id"]
    result = mock_engine.update_task_status(
        record_id=record_id,
        new_status=RecordStatus.in_progress.value,
        agent_id="agent-a",
    )
    assert result["success"] is True
    assert result["status"] == RecordStatus.in_progress.value


def test_update_task_status_not_found(mock_engine: CoordinationEngine):
    result = mock_engine.update_task_status(
        record_id="nonexistent:proj:ts:abc12345",
        new_status="done",
        agent_id="agent-a",
    )
    assert result["success"] is False
    assert result["error"] == "record_not_found"


def test_get_execution_order(mock_engine: CoordinationEngine):
    for i in range(3):
        mock_engine.claim_task(
            agent_id=f"agent-{i}",
            project_id=PROJECT,
            workspace_id=WORKSPACE,
            task_description=f"Task {i}",
            file_paths=[f"src/unique_file_{i}.py"],
        )
    order = mock_engine.get_execution_order(PROJECT, WORKSPACE)
    assert isinstance(order, list)
    assert len(order) >= 1
    for item in order:
        assert "record_id" in item
        assert "agent_id" in item
        assert "status" in item


def test_record_decision(mock_engine: CoordinationEngine):
    claim = mock_engine.claim_task(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        task_description="Auth refactor",
        file_paths=["src/auth.py"],
    )
    result = mock_engine.record_decision(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        decision_text="Use stateless JWT tokens with Redis session store",
        task_id=claim["record_id"],
        affected_files=["src/auth.py"],
    )
    assert result["record_id"]
    assert result["status"] == "recorded"

    # Verify it's retrievable
    record = mock_engine._store.get(result["record_id"])
    assert record is not None
    assert "JWT" in record.text


def test_query_context(mock_engine: CoordinationEngine):
    # Seed some records
    mock_engine.record_decision(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        decision_text="Authentication uses OAuth2 with PKCE flow for security",
        task_id="task-001",
        affected_files=["src/auth.py"],
    )
    mock_engine.record_plan_step(
        agent_id="agent-a",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        step_text="Implement OAuth2 authorization code flow",
        task_id="task-001",
        step_number=1,
        total_steps=3,
    )

    result = mock_engine.query_context(
        question="What authentication approach is being used?",
        project_id=PROJECT,
        workspace_id=WORKSPACE,
        agent_id="agent-c",
    )
    assert "answer" in result
    assert isinstance(result["sources"], list)
    assert isinstance(result["grounded"], bool)
    # Should find at least 1 relevant record
    assert result["grounded"] is True
    assert len(result["sources"]) >= 1


def test_merge_workspace(mock_engine: CoordinationEngine):
    result = mock_engine.merge_workspace(
        agent_id="agent-a",
        project_id=PROJECT,
        source_ws="feature-branch",
        target_ws="main",
        files_changed=["src/auth.py", "src/session.py"],
    )
    assert result["record_id"]
    assert result["status"] == "merged"
    assert set(result["files_changed"]) == {"src/auth.py", "src/session.py"}
