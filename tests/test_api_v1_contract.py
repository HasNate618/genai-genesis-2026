import time
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.agents.railtracks_runtime import CoordinatorAssignment, CoordinatorOutput
from backend.api.v1 import set_runtime
from backend.core.job_runtime import (
    JobRuntime,
    _detect_simple_python_target,
    _extract_primary_py_target,
    _is_coder_recoverable_failure_reason,
    _is_contract_mismatch_reason,
    _is_no_change_reason,
    _is_no_outcome_reason,
    _qa_failure_reason_from_command,
    _resolve_github_repo_name,
    _simple_python_goal_tasks,
    _should_continue_after_coder_result,
    _is_success_status,
    _tasks_from_assignments,
)
from backend.core.workdir_runtime import WorkdirRuntimeError
from backend.main import app


def _wait_for_status(
    client: TestClient, job_id: str, expected: str, timeout_seconds: float = 3.0
) -> dict:
    deadline = time.time() + timeout_seconds
    last_payload: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}/status")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] == expected:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for status '{expected}'. Last payload: {last_payload}")


def _create_client() -> TestClient:
    runtime = JobRuntime(tick_seconds=0.001, memory_factory=lambda _request: None)
    set_runtime(runtime)
    return TestClient(app)


def test_health_contract_shape() -> None:
    with _create_client() as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "agentic-army-v1"}


def test_full_job_lifecycle_with_reviews() -> None:
    with _create_client() as client:
        create = client.post(
            "/api/v1/jobs",
            json={
                "goal": "Align Moorcheh branch to API v1 state machine.",
                "coder_count": 2,
                "gemini_key": "dummy-gemini",
                "moorcheh_key": "dummy-moorcheh",
            },
        )
        assert create.status_code == 200
        job_id = create.json()["job_id"]

        _wait_for_status(client, job_id, "awaiting_plan_approval")

        plan = client.get(f"/api/v1/jobs/{job_id}/plan")
        assert plan.status_code == 200
        assert plan.json()["status"] == "awaiting_plan_approval"
        assert "Align Moorcheh branch" in plan.json()["plan"]

        plan_review = client.post(
            f"/api/v1/jobs/{job_id}/plan/review",
            json={"approved": True, "feedback": "Looks good."},
        )
        assert plan_review.status_code == 200
        assert plan_review.json() == {"ok": True}

        review_ready_payload = _wait_for_status(client, job_id, "review_ready")
        assert isinstance(review_ready_payload["logs"], list)
        assert set(review_ready_payload["agentStates"].keys()) == {
            "planner",
            "coordinator_conflict",
            "coder",
            "merger",
        }

        result_review = client.post(
            f"/api/v1/jobs/{job_id}/result/review",
            json={"approved": True, "feedback": "Ship it."},
        )
        assert result_review.status_code == 200
        assert result_review.json() == {"ok": True}

        done_payload = _wait_for_status(client, job_id, "done")
        assert done_payload["agentStates"]["planner"] == "done"
        assert done_payload["agentStates"]["merger"] == "done"


def test_plan_rejection_loops_back_to_planning() -> None:
    with _create_client() as client:
        create = client.post(
            "/api/v1/jobs",
            json={
                "goal": "Generate a conflict-safe coordination plan.",
                "coder_count": 1,
                "gemini_key": "dummy-gemini",
                "moorcheh_key": "dummy-moorcheh",
            },
        )
        assert create.status_code == 200
        job_id = create.json()["job_id"]

        _wait_for_status(client, job_id, "awaiting_plan_approval")
        first_plan = client.get(f"/api/v1/jobs/{job_id}/plan").json()["plan"]

        rejected = client.post(
            f"/api/v1/jobs/{job_id}/plan/review",
            json={"approved": False, "feedback": "Add stronger conflict mitigation detail."},
        )
        assert rejected.status_code == 200

        _wait_for_status(client, job_id, "awaiting_plan_approval")
        second_plan = client.get(f"/api/v1/jobs/{job_id}/plan").json()["plan"]
        assert second_plan != first_plan
        assert "Add stronger conflict mitigation detail." in second_plan

        approved = client.post(
            f"/api/v1/jobs/{job_id}/plan/review",
            json={"approved": True, "feedback": "Approved now."},
        )
        assert approved.status_code == 200

        _wait_for_status(client, job_id, "review_ready")
        final = client.post(
            f"/api/v1/jobs/{job_id}/result/review",
            json={"approved": True, "feedback": "Done."},
        )
        assert final.status_code == 200
        _wait_for_status(client, job_id, "done")


def test_result_review_rejects_wrong_state() -> None:
    with _create_client() as client:
        create = client.post(
            "/api/v1/jobs",
            json={
                "goal": "Test result gate validation.",
                "coder_count": 1,
                "gemini_key": "dummy-gemini",
                "moorcheh_key": "dummy-moorcheh",
            },
        )
        assert create.status_code == 200
        job_id = create.json()["job_id"]

        response = client.post(
            f"/api/v1/jobs/{job_id}/result/review",
            json={"approved": True, "feedback": "Too early."},
        )
        assert response.status_code == 409


def test_create_job_accepts_no_user_api_keys() -> None:
    with _create_client() as client:
        create = client.post(
            "/api/v1/jobs",
            json={
                "goal": "Run with hosted LLM endpoint and no user model key.",
                "coder_count": 2,
                "github_token": "gho_dummy_token",
                "github_repo": "owner/repo",
                "base_branch": "main",
            },
        )
        assert create.status_code == 200
        job_id = create.json()["job_id"]
        payload = _wait_for_status(client, job_id, "awaiting_plan_approval")
        assert payload["status"] == "awaiting_plan_approval"


def test_create_job_rejects_invalid_workspace_path() -> None:
    with _create_client() as client:
        invalid_path = f"/tmp/agenticarmy-not-a-real-workspace-path-{uuid4().hex}"
        create = client.post(
            "/api/v1/jobs",
            json={
                "goal": "Run with invalid workspace path.",
                "coder_count": 1,
                "workspace_path": invalid_path,
            },
        )
        assert create.status_code == 422
        assert "workspace_path" in create.text


def test_status_payload_contains_agent_results() -> None:
    with _create_client() as client:
        create = client.post(
            "/api/v1/jobs",
            json={
                "goal": "Ensure status payload includes agent artifact output.",
                "coder_count": 1,
            },
        )
        assert create.status_code == 200
        job_id = create.json()["job_id"]
        payload = _wait_for_status(client, job_id, "awaiting_plan_approval")
        assert "agentResults" in payload
        assert set(payload["agentResults"].keys()) == {
            "planner",
            "coordinator_conflict",
            "coder",
            "merger",
        }
        assert "artifacts" in payload
        assert payload["artifacts"]["base_branch"] == "main"
        assert payload["artifacts"]["merged_branches"] == []
        assert payload["artifacts"]["merged_commit"] == ""
        assert payload["artifacts"]["changed_files"] == []


def test_unknown_job_status_returns_failed_payload_for_polling() -> None:
    with _create_client() as client:
        response = client.get("/api/v1/jobs/does-not-exist/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "failed"
        assert "backend restarted" in payload["logs"][0].lower()
        assert set(payload["agentStates"].keys()) == {
            "planner",
            "coordinator_conflict",
            "coder",
            "merger",
        }
        assert payload["artifacts"]["merged_branches"] == []
        assert payload["artifacts"]["merged_commit"] == ""
        assert payload["artifacts"]["changed_files"] == []


def test_success_status_aliases_are_accepted() -> None:
    assert _is_success_status("completed")
    assert _is_success_status("success")
    assert _is_success_status("ok")
    assert _is_success_status("done")
    assert not _is_success_status("failed")


def test_contract_mismatch_reason_detection_supports_multiple_phrasings() -> None:
    assert _is_contract_mismatch_reason(
        "Assistant response did not conform to the required output contract."
    )
    assert _is_contract_mismatch_reason(
        "The assistant's response does not conform to the required output contract; required fields are missing or malformed."
    )
    assert _is_contract_mismatch_reason(
        "Assistant response did not follow the required output contract; returned an unrelated JSON with rel_path."
    )
    assert not _is_contract_mismatch_reason("Transient network timeout")


def test_no_change_reason_is_recoverable() -> None:
    reason = "No implementation or file changes were provided for the assigned task."
    assert _is_no_change_reason(reason)
    assert _is_coder_recoverable_failure_reason(reason)


def test_no_outcome_reason_is_recoverable() -> None:
    reason = "No implementation outcome was provided by the coding agent."
    assert _is_no_outcome_reason(reason)
    assert _is_coder_recoverable_failure_reason(reason)


def test_no_outcome_reason_catches_no_coding_actions_phrasing() -> None:
    assert _is_no_outcome_reason("No coding actions were performed; implementation outcome is missing.")
    assert _is_no_outcome_reason("No coding was performed for the assigned task.")
    assert _is_no_outcome_reason("Implementation outcome is missing from the agent response.")
    assert _is_no_outcome_reason("No files were created during execution.")
    assert _is_no_outcome_reason("No files were written to the workspace.")
    assert _is_no_outcome_reason("No changes were made to any files.")
    assert not _is_no_outcome_reason("Transient network error occurred.")


def test_extract_primary_py_target_returns_first_py_file() -> None:
    tasks = _simple_python_goal_tasks("calc.py")
    assert _extract_primary_py_target(tasks, "build a calc") == "calc.py"


def test_extract_primary_py_target_falls_back_to_main_for_python_goal() -> None:
    from backend.memory.conflict_context import TaskDraft
    tasks = [TaskDraft(task_id="t1", agent_id="coder-1", file_paths=["README.md", "docs/spec.md"])]
    assert _extract_primary_py_target(tasks, "build a python app") == "main.py"
    assert _extract_primary_py_target(tasks, "build an app") is None


def test_detect_simple_python_target_matches_calc_keyword() -> None:
    assert _detect_simple_python_target("build a python calc program") == "calc.py"
    assert _detect_simple_python_target("create a python terminal calc") == "calc.py"


def test_detect_simple_python_target_prefers_explicit_file_then_hello_world_default() -> None:
    assert _detect_simple_python_target("Create hello world in python at scripts/greeter.py") == "scripts/greeter.py"
    assert _detect_simple_python_target("Make hello world in python") == "hello_world.py"
    assert _detect_simple_python_target("Create a python script at scripts/greeter.py") is None
    assert _detect_simple_python_target("Write hello world in javascript") is None


def test_detect_simple_python_target_matches_calculator_and_other_goals() -> None:
    assert _detect_simple_python_target("Create a python terminal based calculator") == "calculator.py"
    assert _detect_simple_python_target("Build a Python calculator at calc.py") == "calc.py"
    assert _detect_simple_python_target("Make a python guessing game") == "guessing_game.py"
    assert _detect_simple_python_target("Write a python command-line todo list") == "todo_list.py"
    assert _detect_simple_python_target("Write a python terminal-based script") == "main.py"
    assert _detect_simple_python_target("Build a web app with flask") is None


def test_simple_python_goal_tasks_targets_single_file() -> None:
    tasks = _simple_python_goal_tasks("hello_world.py")
    assert len(tasks) == 1
    assert tasks[0].file_paths == ["hello_world.py"]
    assert tasks[0].agent_id == "coder-1"


def test_tasks_from_assignments_infers_concrete_files_for_python_goal() -> None:
    coordinator = CoordinatorOutput(
        assignments=[
            CoordinatorAssignment(
                task_id="task-01",
                task_summary="Initialize package, add README, and define dependencies",
                assigned_agent_id="coder-1",
                rationale="Set up snake game project scaffold.",
            ),
            CoordinatorAssignment(
                task_id="task-02",
                task_summary="Implement game loop and command line entrypoint",
                assigned_agent_id="coder-1",
                rationale="Provide playable snake game loop and CLI.",
            ),
        ]
    )
    tasks = _tasks_from_assignments(
        coordinator,
        coder_count=1,
        goal="Build a snake game in Python",
    )
    flattened = [path for task in tasks for path in task.file_paths]
    assert "README.md" in flattened
    assert "requirements.txt" in flattened
    assert any(path.startswith("snake_game/") for path in flattened)
    assert all(not path.startswith("workspace/task_") for path in flattened)


def test_tasks_from_assignments_ignores_placeholder_predicted_files() -> None:
    coordinator = CoordinatorOutput(
        assignments=[
            CoordinatorAssignment(
                task_id="task-01",
                task_summary="Update docs",
                assigned_agent_id="coder-1",
                predicted_files=["workspace/task_1.txt", "README.md"],
            )
        ]
    )
    tasks = _tasks_from_assignments(
        coordinator,
        coder_count=1,
        goal="Update README documentation",
    )
    assert tasks[0].file_paths == ["README.md"]


def test_resolve_github_repo_name_prefers_explicit_repo() -> None:
    class _Workdirs:
        def detect_repo_full_name(self) -> str:
            raise AssertionError("should not be called when explicit repo is provided")

    assert _resolve_github_repo_name("owner/explicit", _Workdirs()) == "owner/explicit"


def test_resolve_github_repo_name_uses_detected_remote() -> None:
    class _Workdirs:
        def detect_repo_full_name(self) -> str:
            return "owner/from-remote"

    assert _resolve_github_repo_name("", _Workdirs()) == "owner/from-remote"


def test_resolve_github_repo_name_returns_empty_when_remote_missing() -> None:
    class _Workdirs:
        def detect_repo_full_name(self) -> str:
            raise WorkdirRuntimeError("remote.origin.url is not configured.")

    assert _resolve_github_repo_name("", _Workdirs()) == ""


def test_qa_failure_reason_from_command_prefers_last_line() -> None:
    detail = _qa_failure_reason_from_command(
        {"exit_code": 1, "stdout": "", "stderr": "line one\nline two\nAssertionError: x"}
    )
    assert "pytest failed (exit 1)" in detail
    assert "AssertionError: x" in detail


def test_should_continue_after_coder_result_when_committed_changes_exist() -> None:
    assert _should_continue_after_coder_result(
        status="failed",
        reason="Generated code contains syntax errors",
        committed=True,
    )
    assert not _should_continue_after_coder_result(
        status="failed",
        reason="Tool execution failed with exit code 2",
        committed=False,
    )
