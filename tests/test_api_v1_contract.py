import time

from fastapi.testclient import TestClient

from backend.api.v1 import set_runtime
from backend.core.job_runtime import JobRuntime
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
            "conflict_manager",
            "coder",
            "verification",
        }

        result_review = client.post(
            f"/api/v1/jobs/{job_id}/result/review",
            json={"approved": True, "feedback": "Ship it."},
        )
        assert result_review.status_code == 200
        assert result_review.json() == {"ok": True}

        done_payload = _wait_for_status(client, job_id, "done")
        assert done_payload["agentStates"]["planner"] == "done"
        assert done_payload["agentStates"]["verification"] == "done"


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

