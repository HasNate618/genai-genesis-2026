"""
AgenticArmy API Routes
Workflow implementation with human-in-the-loop gates and explicit retry loops.
"""

import asyncio
import os
import uuid
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.agents.runtime import AgentRuntimeError, run_contract_agent

router = APIRouter(prefix="/api/v1")

# ── In-memory job store ───────────────────────────────────────────
_jobs: dict[str, dict] = {}

# Event locks for the two human-in-the-loop gates
_plan_events: dict[str, asyncio.Event] = {}
_result_events: dict[str, asyncio.Event] = {}

_AGENT_STATE_ALIASES = {
    # New logical agent names
    "planner": ("planner",),
    "task_coordinator": ("task_coordinator", "conflict_manager"),
    "conflict_analyst": ("conflict_analyst", "conflict_manager"),
    "user_agents": ("user_agents", "coder"),
    "merge_agent": ("merge_agent", "verification"),
    "qa_agent": ("qa_agent", "verification"),
}


# ── Schemas ───────────────────────────────────────────────────────
class JobCreateReq(BaseModel):
    goal: str
    coder_count: int = 2
    gemini_key: str
    moorcheh_key: Optional[str] = ""


class ReviewReq(BaseModel):
    approved: bool
    feedback: Optional[str] = ""


# ── Helpers ───────────────────────────────────────────────────────
def _initial_agent_states() -> dict[str, str]:
    keys = {alias for aliases in _AGENT_STATE_ALIASES.values() for alias in aliases}
    return {key: "idle" for key in sorted(keys)}


def _new_job(goal: str, coder_count: int) -> dict[str, Any]:
    return {
        "goal": goal,
        "coder_count": coder_count,
        "status": "initializing",
        "logs": [],
        "plan": None,
        "plan_approved": None,
        "plan_feedback": None,
        "task_distribution": None,
        "conflict_report": None,
        "user_agent_outputs": [],
        "merge_result": None,
        "qa_result": None,
        "result_approved": None,
        "result_feedback": None,
        "workflow_context": {
            "replan_reason": None,
            "coordinator_feedback": None,
            "execution_feedback": None,
        },
        "planning_round": 0,
        "coordination_round": 0,
        "execution_round": 0,
        "agent_states": _initial_agent_states(),
        "created_at": datetime.utcnow().isoformat(),
    }


def _set_agent_state(job: dict[str, Any], logical_key: str, state: str) -> None:
    aliases = _AGENT_STATE_ALIASES.get(logical_key, (logical_key,))
    for key in aliases:
        job["agent_states"][key] = state


def _set_all_non_planner_idle(job: dict[str, Any]) -> None:
    for key in ("task_coordinator", "conflict_analyst", "user_agents", "merge_agent", "qa_agent"):
        _set_agent_state(job, key, "idle")


def _log(job: dict[str, Any], message: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    job["logs"].append(f"[{ts}] {message}")


def _is_simulation_mode(req: JobCreateReq) -> bool:
    key = req.gemini_key or ""
    return key.startswith(("test-", "dummy-")) or os.getenv("AGENTIC_ARMY_SIMULATE") == "1"


def _public_agent_states(job: dict[str, Any]) -> dict[str, str]:
    # Keep legacy contract shape while allowing richer internal state aliases.
    states = job.get("agent_states") or {}
    return {
        "planner": states.get("planner", "idle"),
        "conflict_manager": states.get("conflict_manager", "idle"),
        "coder": states.get("coder", "idle"),
        "verification": states.get("verification", "idle"),
    }


def _build_agent_catalog(req: JobCreateReq) -> list[dict[str, Any]]:
    return [
        {
            "id": f"coder-{idx + 1}",
            "role": "coding_agent",
            "capabilities": ["implementation", "integration", "refactoring"],
            "constraints": [],
            "current_load": 0,
        }
        for idx in range(max(1, req.coder_count))
    ]


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _runtime_model_override() -> str | None:
    model = (os.getenv("AGENTIC_ARMY_GEMINI_MODEL") or "").strip()
    return model or None


def _actual_coding_parallelism(default_parallelism: int) -> int:
    configured = os.getenv("AGENTIC_ARMY_CODING_PARALLELISM")
    if configured is None:
        # Default to sequential coding calls in actual-agent mode to reduce request burst quota usage.
        return 1
    return max(1, _safe_int(configured, default_parallelism))


async def _workflow_sleep(req: JobCreateReq, seconds: float) -> None:
    if _is_simulation_mode(req):
        return
    await asyncio.sleep(seconds)


# ── Routes ────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    """Health check ping."""
    return {"status": "ok", "service": "agentic-army-v1"}


@router.post("/jobs")
async def start_job(req: JobCreateReq):
    """
    Step 1: Goal Input
    Starts workflow pipeline in a background task.
    """
    job_id = str(uuid.uuid4())
    job = _new_job(req.goal, req.coder_count)
    _jobs[job_id] = job

    _plan_events[job_id] = asyncio.Event()
    _result_events[job_id] = asyncio.Event()

    asyncio.create_task(_run_pipeline(job_id, req))
    return {"job_id": job_id}


@router.get("/jobs/{job_id}/plan")
async def get_plan(job_id: str):
    """
    Returns current plan payload during planning/approval stages.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "status": job["status"],
        "plan": job["plan"],
    }


@router.post("/jobs/{job_id}/plan/review")
async def review_plan(job_id: str, req: ReviewReq):
    """
    HitL gate 1: plan approve/reject.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "awaiting_plan_approval":
        raise HTTPException(status_code=409, detail="Plan review is only allowed while awaiting_plan_approval")

    job["plan_approved"] = req.approved
    job["plan_feedback"] = (req.feedback or "").strip()

    event = _plan_events.get(job_id)
    if event:
        event.set()

    return {"ok": True}


@router.get("/jobs/{job_id}/status")
async def get_status(job_id: str):
    """
    Poll workflow status, logs, and agent states.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "status": job["status"],
        "logs": job["logs"],
        "agentStates": _public_agent_states(job),
        "taskDistribution": job["task_distribution"],
        "conflictReport": job["conflict_report"],
        "mergeResult": job["merge_result"],
        "qaResult": job["qa_result"],
    }


@router.post("/jobs/{job_id}/result/review")
async def review_result(job_id: str, req: ReviewReq):
    """
    HitL gate 2: final output approve/reject.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "review_ready":
        raise HTTPException(status_code=409, detail="Result review is only allowed while review_ready")

    job["result_approved"] = req.approved
    job["result_feedback"] = (req.feedback or "").strip()

    event = _result_events.get(job_id)
    if event:
        event.set()

    return {"ok": True}


# ── Workflow helpers ──────────────────────────────────────────────
def _build_stub_plan(req: JobCreateReq, plan_round: int, feedback: str) -> str:
    feedback_line = f"\n**Revision Context:** {feedback}\n" if feedback else "\n"
    return (
        f"## Technical Roadmap (v{plan_round})\n\n"
        f"**Goal:** {req.goal}{feedback_line}\n"
        f"**Execution Tasks:**\n"
        f"1. Coordinate {req.coder_count} coding agent(s) across scoped tasks\n"
        f"2. Evaluate overlap risk and rebalance assignments when needed\n"
        f"3. Merge outputs and run QA before final user delivery\n"
    )


def _build_task_distribution(req: JobCreateReq, coordination_round: int, context: dict[str, Any] | None) -> dict[str, Any]:
    context_reason = (context or {}).get("reason")
    task_count = max(3, req.coder_count + 1)
    assignments: list[dict[str, Any]] = []
    for index in range(task_count):
        assignee = f"coder-{(index % max(1, req.coder_count)) + 1}"
        assignments.append(
            {
                "task_id": f"task-{index + 1:02d}",
                "task_summary": f"Implement workflow slice {index + 1}",
                "assigned_agent_id": assignee,
                "phase": "execution",
                "depends_on": [f"task-{index:02d}"] if index > 0 else [],
            }
        )
    return {
        "status": "ok",
        "coordination_round": coordination_round,
        "context_applied": bool(context),
        "context_reason": context_reason or "",
        "assignments": assignments,
    }


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.lower().split())


def _is_near_duplicate_task(summary_a: Any, summary_b: Any) -> bool:
    a = _normalized_text(summary_a)
    b = _normalized_text(summary_b)
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.97


def _build_conflict_formula_inputs(
    req: JobCreateReq,
    task_distribution: dict[str, Any] | None,
) -> dict[str, float]:
    assignments = [
        item
        for item in ((task_distribution or {}).get("assignments") or [])
        if isinstance(item, dict)
    ]

    task_owner: dict[str, str] = {}
    for assignment in assignments:
        task_id = assignment.get("task_id")
        agent_id = assignment.get("assigned_agent_id")
        if isinstance(task_id, str) and task_id and isinstance(agent_id, str) and agent_id:
            task_owner[task_id] = agent_id

    dependency_edges = 0
    cross_agent_dependency_edges = 0
    for assignment in assignments:
        assigned_agent = assignment.get("assigned_agent_id")
        depends_on = assignment.get("depends_on")
        if not isinstance(assigned_agent, str) or not isinstance(depends_on, list):
            continue
        for dependency in depends_on:
            if not isinstance(dependency, str):
                continue
            dependency_edges += 1
            owner = task_owner.get(dependency)
            if owner and owner != assigned_agent:
                cross_agent_dependency_edges += 1

    total_tasks = max(1, len(assignments))
    shared_dependency_ratio = min(1.0, cross_agent_dependency_edges / total_tasks)

    parallelism_pressure = min(1.0, max(0.0, (max(1, req.coder_count) - 2) / 6.0))
    adjusted_shared_dependency_ratio = min(
        1.0,
        shared_dependency_ratio + (parallelism_pressure * 0.25),
    )

    cross_agent_pairs = 0
    similar_pairs = 0
    same_category_similar_pairs = 0

    for i in range(len(assignments)):
        left = assignments[i]
        left_agent = left.get("assigned_agent_id")
        if not isinstance(left_agent, str):
            continue
        for j in range(i + 1, len(assignments)):
            right = assignments[j]
            right_agent = right.get("assigned_agent_id")
            if not isinstance(right_agent, str) or left_agent == right_agent:
                continue

            cross_agent_pairs += 1
            similar = _is_near_duplicate_task(
                left.get("task_summary"),
                right.get("task_summary"),
            )
            if not similar:
                continue

            similar_pairs += 1
            left_phase = _normalized_text(left.get("phase"))
            right_phase = _normalized_text(right.get("phase"))
            if left_phase and left_phase == right_phase:
                same_category_similar_pairs += 1

    task_similarity_ratio = (
        similar_pairs / max(1, cross_agent_pairs)
        if cross_agent_pairs
        else 0.0
    )
    same_category_task_ratio = (
        same_category_similar_pairs / max(1, similar_pairs)
        if similar_pairs
        else 0.0
    )

    return {
        "shared_dependency_ratio": shared_dependency_ratio,
        "adjusted_shared_dependency_ratio": adjusted_shared_dependency_ratio,
        "task_similarity_ratio": task_similarity_ratio,
        "same_category_task_ratio": same_category_task_ratio,
        "parallelism_pressure": parallelism_pressure,
        "cross_agent_dependency_edges": float(cross_agent_dependency_edges),
        "dependency_edges": float(dependency_edges),
        "cross_agent_pairs": float(cross_agent_pairs),
        "similar_pairs": float(similar_pairs),
    }


def _build_conflict_report(
    req: JobCreateReq,
    coordination_round: int,
    coordinator_context: dict[str, Any] | None,
    task_distribution: dict[str, Any] | None,
) -> dict[str, Any]:
    threshold = 20
    signals = _build_conflict_formula_inputs(req, task_distribution)

    raw_score = (
        (signals["adjusted_shared_dependency_ratio"] * 0.2)
        + (signals["task_similarity_ratio"] * 0.5)
        + (signals["same_category_task_ratio"] * 0.3)
    ) * 100.0

    mitigation = 0.0
    if coordination_round > 1:
        mitigation += min(0.45, (coordination_round - 1) * 0.18)

    if coordinator_context:
        source = coordinator_context.get("source")
        if source in {"conflict_analysis", "merge_failure"}:
            mitigation += 0.10
        elif source:
            mitigation += 0.05
    mitigation = min(0.65, mitigation)

    score = int(round(max(0.0, min(95.0, raw_score * (1.0 - mitigation)))))
    breached = score >= threshold
    return {
        "status": "ok",
        "coordination_round": coordination_round,
        "overall_conflict_score": score,
        "threshold_percent": threshold,
        "threshold_breached": breached,
        # Contract-aligned fields
        "is_acceptable": not breached,
        "agent_pair_scores": [],
        "task_hotspots": [],
        "warnings": [],
        "next_action": "rerun_task_coordinator" if breached else "proceed_to_user_agents",
        "next_action_reason": (
            f"Conflict score {score}% exceeded threshold {threshold}%."
            if breached
            else "Conflict score within acceptable threshold."
        ),
        "formula_signals": {
            "shared_dependency_ratio": round(signals["shared_dependency_ratio"], 4),
            "adjusted_shared_dependency_ratio": round(signals["adjusted_shared_dependency_ratio"], 4),
            "task_similarity_ratio": round(signals["task_similarity_ratio"], 4),
            "same_category_task_ratio": round(signals["same_category_task_ratio"], 4),
            "parallelism_pressure": round(signals["parallelism_pressure"], 4),
            "raw_score": round(raw_score, 2),
            "mitigation_applied": round(mitigation, 4),
        },
    }


def _build_user_agent_outputs(
    req: JobCreateReq,
    execution_round: int,
    execution_context: dict[str, Any] | None,
    task_distribution: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    assignments = (task_distribution or {}).get("assignments") or []
    outputs: list[dict[str, Any]] = []
    grouped: dict[str, list[str]] = {}

    for assignment in assignments:
        grouped.setdefault(assignment["assigned_agent_id"], []).append(assignment["task_id"])

    for agent_id, task_ids in grouped.items():
        outputs.append(
            {
                "agent_id": agent_id,
                "task_ids": task_ids,
                "status": "completed",
                "changed_files": [f"src/generated/{agent_id}_round_{execution_round}.py"],
                "patch_summary": (
                    "Retry-aware patch generated with QA feedback context."
                    if execution_context
                    else "Initial patch generated from approved task assignments."
                ),
            }
        )

    if not outputs:
        for idx in range(max(1, req.coder_count)):
            outputs.append(
                {
                    "agent_id": f"coder-{idx + 1}",
                    "task_ids": [f"task-fallback-{idx + 1}"],
                    "status": "completed",
                    "changed_files": [f"src/generated/coder_{idx + 1}_round_{execution_round}.py"],
                    "patch_summary": "Fallback output due to missing explicit assignments.",
                }
            )

    return outputs


def _build_merge_result(
    req: JobCreateReq,
    execution_round: int,
    coordinator_context: dict[str, Any] | None,
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    recover_from_merge_feedback = bool(
        coordinator_context and coordinator_context.get("source") == "merge_failure"
    )
    should_fail = req.coder_count >= 7 and not recover_from_merge_feedback and execution_round == 1

    if should_fail:
        return {
            "status": "failed",
            "mergeable": False,
            "summary": {
                "total_outputs": len(outputs),
                "files_touched": sum(len(item.get("changed_files", [])) for item in outputs),
                "conflicts_detected": 2,
                "conflicts_resolved": 0,
            },
            "next_action": "rerun_task_coordinator",
            "next_action_reason": "Unresolved file overlap across parallel coder outputs.",
            "unresolved_conflicts": [
                {
                    "file": "src/generated/shared_workflow.py",
                    "agents_involved": [item["agent_id"] for item in outputs[:2]],
                    "reason": "Competing edits to the same integration surface.",
                }
            ],
        }

    return {
        "status": "success",
        "mergeable": True,
        "summary": {
            "total_outputs": len(outputs),
            "files_touched": sum(len(item.get("changed_files", [])) for item in outputs),
            "conflicts_detected": 0,
            "conflicts_resolved": 0,
        },
        "next_action": "proceed_to_qa",
        "next_action_reason": "Merge succeeded without unresolved conflicts.",
        "unresolved_conflicts": [],
    }


def _build_qa_result(
    req: JobCreateReq,
    execution_round: int,
    execution_context: dict[str, Any] | None,
) -> dict[str, Any]:
    should_fail = req.coder_count >= 8 and not execution_context
    if should_fail:
        return {
            "status": "failed",
            "qa_passed": False,
            "summary": {
                "commands_run": 2,
                "commands_passed": 1,
                "commands_failed": 1,
            },
            "failure_report": {
                "root_causes": ["Demo smoke test failed during integration assertion checks."],
                "failed_commands": ["./run_demo.sh"],
            },
            "next_action": "rerun_user_agents",
            "next_action_reason": "Functional QA failed; regenerate coder outputs with failure context.",
        }

    return {
        "status": "success",
        "qa_passed": True,
        "summary": {
            "commands_run": 2,
            "commands_passed": 2,
            "commands_failed": 0,
        },
        "failure_report": {
            "root_causes": [],
            "failed_commands": [],
        },
        "next_action": "await_user_approval",
        "next_action_reason": "QA checks passed.",
    }


async def _run_planning_agent(
    req: JobCreateReq,
    plan_round: int,
    feedback: str,
    revision_source: str,
) -> str:
    if _is_simulation_mode(req):
        return _build_stub_plan(req, plan_round, feedback)

    payload = {
        "goal": req.goal,
        "plan_round": plan_round,
        "revision_context": {
            "source": revision_source,
            "feedback": feedback,
        },
        "constraints": {
            "max_coder_agents": max(1, req.coder_count),
        },
    }

    try:
        result = await run_contract_agent(
            "planning_agent.md",
            payload,
            req.gemini_key,
            model=_runtime_model_override(),
        )
    except AgentRuntimeError as exc:
        raise RuntimeError(f"Planning agent runtime failed: {exc}") from exc

    plan = result.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        raise RuntimeError(f"Planning agent returned invalid plan payload: {result!r}")
    return plan


async def _run_task_coordinator_agent(
    req: JobCreateReq,
    coordination_round: int,
    coordinator_context: dict[str, Any] | None,
    plan: str,
) -> dict[str, Any]:
    if _is_simulation_mode(req):
        return _build_task_distribution(req, coordination_round, coordinator_context)

    context_reason = (coordinator_context or {}).get("reason") or ""
    payload = {
        "goal": req.goal,
        "plan": plan,
        "plan_approval": {"approved": True},
        "agents": _build_agent_catalog(req),
        "loop_context": {
            "source": (coordinator_context or {}).get("source") or "none",
            "reason": context_reason,
        },
        "constraints": {
            "max_parallel_agents": max(1, req.coder_count),
            "must_review_dependencies": True,
        },
    }

    try:
        result = await run_contract_agent(
            "task_coordinator_agent.md",
            payload,
            req.gemini_key,
            model=_runtime_model_override(),
        )
    except AgentRuntimeError as exc:
        raise RuntimeError(f"Task coordinator runtime failed: {exc}") from exc

    assignments = result.get("assignments")
    if not isinstance(assignments, list):
        raise RuntimeError(f"Task coordinator returned invalid assignments payload: {result!r}")

    normalized = dict(result)
    normalized["status"] = result.get("status") or "ok"
    normalized["coordination_round"] = coordination_round
    normalized["context_applied"] = bool(coordinator_context)
    normalized["context_reason"] = context_reason
    normalized["assignments"] = assignments
    return normalized


async def _run_conflict_analysis_agent(
    req: JobCreateReq,
    coordination_round: int,
    coordinator_context: dict[str, Any] | None,
    task_distribution: dict[str, Any] | None,
    plan: str,
) -> dict[str, Any]:
    if _is_simulation_mode(req):
        return _build_conflict_report(
            req,
            coordination_round,
            coordinator_context,
            task_distribution,
        )

    payload = {
        "goal": req.goal,
        "plan": plan,
        "task_distribution": task_distribution or {"assignments": []},
        "agents": _build_agent_catalog(req),
        "constraints": {
            "conflict_threshold_percent": 20,
        },
    }

    try:
        result = await run_contract_agent(
            "conflict_analysis_agent.md",
            payload,
            req.gemini_key,
            model=_runtime_model_override(),
        )
    except AgentRuntimeError as exc:
        raise RuntimeError(f"Conflict analysis runtime failed: {exc}") from exc

    score = _safe_int(result.get("overall_conflict_score"), 0)
    threshold = _safe_int(result.get("threshold_percent"), 20)
    breached = (
        bool(result["threshold_breached"])
        if "threshold_breached" in result
        else score >= threshold
    )

    normalized = dict(result)
    normalized["status"] = result.get("status") or "ok"
    normalized["coordination_round"] = coordination_round
    normalized["overall_conflict_score"] = score
    normalized["threshold_percent"] = threshold
    normalized["threshold_breached"] = breached
    normalized["next_action"] = result.get("next_action") or (
        "rerun_task_coordinator" if breached else "proceed_to_user_agents"
    )
    normalized["next_action_reason"] = result.get("next_action_reason") or (
        f"Conflict score {score}% exceeded threshold {threshold}%."
        if breached
        else "Conflict score within acceptable threshold."
    )
    return normalized


def _group_assignments_by_agent(
    req: JobCreateReq,
    task_distribution: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    assignments = (task_distribution or {}).get("assignments") or []
    grouped: dict[str, list[dict[str, Any]]] = {}

    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        agent_id = assignment.get("assigned_agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            continue
        grouped.setdefault(agent_id, []).append(assignment)

    if grouped:
        return grouped

    for idx in range(max(1, req.coder_count)):
        agent_id = f"coder-{idx + 1}"
        grouped[agent_id] = [
            {
                "task_id": f"task-fallback-{idx + 1}",
                "task_summary": f"Fallback coding task for {agent_id}.",
                "assigned_agent_id": agent_id,
                "phase": "execution",
                "depends_on": [],
            }
        ]
    return grouped


async def _run_coding_agents(
    req: JobCreateReq,
    execution_round: int,
    execution_context: dict[str, Any] | None,
    task_distribution: dict[str, Any] | None,
    plan: str,
) -> list[dict[str, Any]]:
    if _is_simulation_mode(req):
        return _build_user_agent_outputs(req, execution_round, execution_context, task_distribution)

    grouped_assignments = _group_assignments_by_agent(req, task_distribution)
    retry_source = (execution_context or {}).get("source") or "none"
    retry_reason = (execution_context or {}).get("reason") or ""
    failure_report = (execution_context or {}).get("failure_report")
    if not isinstance(failure_report, dict):
        failure_report = {
            "root_causes": [],
            "failed_commands": [],
        }

    async def _run_assignee(agent_id: str, task_list: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "goal": req.goal,
            "plan": plan,
            "assigned_agent_id": agent_id,
            "task_list": task_list,
            "retry_context": {
                "source": retry_source,
                "reason": retry_reason,
                "failure_report": failure_report,
            },
        }
        try:
            result = await run_contract_agent(
                "coding_agent.md",
                payload,
                req.gemini_key,
                model=_runtime_model_override(),
            )
        except AgentRuntimeError as exc:
            raise RuntimeError(f"Coding agent runtime failed for {agent_id}: {exc}") from exc

        task_ids = [
            item.get("task_id")
            for item in task_list
            if isinstance(item, dict) and isinstance(item.get("task_id"), str)
        ]
        patch_summary = result.get("patch_summary")
        if not isinstance(patch_summary, str) or not patch_summary.strip():
            patch_summary = "No patch summary returned by coding agent."

        output = {
            "agent_id": agent_id,
            "task_ids": task_ids,
            "status": result.get("status") or "completed",
            "changed_files": _string_list(result.get("changed_files")),
            "patch_summary": patch_summary,
        }
        if isinstance(result.get("next_action"), str):
            output["next_action"] = result["next_action"]
        return output

    ordered_agent_ids = sorted(grouped_assignments.keys())
    parallelism = min(
        len(ordered_agent_ids),
        _actual_coding_parallelism(default_parallelism=max(1, req.coder_count)),
    )
    if parallelism <= 1:
        outputs: list[dict[str, Any]] = []
        for index, agent_id in enumerate(ordered_agent_ids):
            outputs.append(await _run_assignee(agent_id, grouped_assignments[agent_id]))
            # Small pacing delay to reduce request burst pressure on free/limited quotas.
            if index < len(ordered_agent_ids) - 1:
                await asyncio.sleep(0.35)
        return outputs

    semaphore = asyncio.Semaphore(parallelism)

    async def _run_limited(agent_id: str) -> dict[str, Any]:
        async with semaphore:
            return await _run_assignee(agent_id, grouped_assignments[agent_id])

    tasks = [_run_limited(agent_id) for agent_id in ordered_agent_ids]
    return await asyncio.gather(*tasks)


async def _run_merge_agent(
    req: JobCreateReq,
    execution_round: int,
    coordinator_context: dict[str, Any] | None,
    outputs: list[dict[str, Any]],
    task_distribution: dict[str, Any] | None,
    plan: str,
) -> dict[str, Any]:
    if _is_simulation_mode(req):
        return _build_merge_result(req, execution_round, coordinator_context, outputs)

    payload = {
        "goal": req.goal,
        "plan": plan,
        "task_distribution": task_distribution or {"assignments": []},
        "agent_outputs": outputs,
        "constraints": {
            "allow_auto_resolution": True,
        },
    }

    try:
        result = await run_contract_agent(
            "merge_agent.md",
            payload,
            req.gemini_key,
            model=_runtime_model_override(),
        )
    except AgentRuntimeError as exc:
        raise RuntimeError(f"Merge agent runtime failed: {exc}") from exc

    summary = result.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    status = result.get("status") or "failed"
    mergeable = bool(result.get("mergeable")) if "mergeable" in result else status == "success"

    normalized = dict(result)
    normalized["status"] = status
    normalized["mergeable"] = mergeable
    normalized["summary"] = {
        "total_outputs": _safe_int(summary.get("total_outputs"), len(outputs)),
        "files_touched": _safe_int(
            summary.get("files_touched"),
            sum(len(item.get("changed_files", [])) for item in outputs),
        ),
        "conflicts_detected": _safe_int(summary.get("conflicts_detected"), 0),
        "conflicts_resolved": _safe_int(summary.get("conflicts_resolved"), 0),
    }
    normalized["unresolved_conflicts"] = result.get("unresolved_conflicts") or []
    normalized["next_action"] = result.get("next_action") or (
        "proceed_to_qa" if mergeable else "rerun_task_coordinator"
    )
    normalized["next_action_reason"] = result.get("next_action_reason") or (
        "Merge succeeded without unresolved conflicts."
        if mergeable
        else "Merge failed due to unresolved conflicts."
    )
    return normalized


async def _run_qa_agent(
    req: JobCreateReq,
    execution_round: int,
    execution_context: dict[str, Any] | None,
    merge_result: dict[str, Any] | None,
    user_agent_outputs: list[dict[str, Any]],
    plan: str,
) -> dict[str, Any]:
    if _is_simulation_mode(req):
        return _build_qa_result(req, execution_round, execution_context)

    files_touched = sorted(
        {
            file_path
            for output in user_agent_outputs
            for file_path in _string_list(output.get("changed_files"))
        }
    )
    payload = {
        "goal": req.goal,
        "plan": plan,
        "merged_output": {
            "status": (merge_result or {}).get("status") or "unknown",
            "files_touched": files_touched,
        },
        "workspace_path": os.getcwd(),
        "run_command": "python3 -m compileall backend",
        "test_commands": [],
        "constraints": {
            "stop_on_first_failure": False,
            "max_log_bytes_per_command": 2_000_000,
        },
        "copilot_code_review": {
            "enabled": True,
            "scope": "changed_files",
        },
    }

    try:
        result = await run_contract_agent(
            "qa_agent.md",
            payload,
            req.gemini_key,
            model=_runtime_model_override(),
        )
    except AgentRuntimeError as exc:
        raise RuntimeError(f"QA agent runtime failed: {exc}") from exc

    summary = result.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    failure_report = result.get("failure_report")
    if not isinstance(failure_report, dict):
        failure_report = {}

    status = result.get("status") or "failed"
    qa_passed = bool(result.get("qa_passed")) if "qa_passed" in result else status == "success"

    normalized = dict(result)
    normalized["status"] = status
    normalized["qa_passed"] = qa_passed
    normalized["summary"] = {
        "commands_run": _safe_int(summary.get("commands_run"), 0),
        "commands_passed": _safe_int(summary.get("commands_passed"), 0),
        "commands_failed": _safe_int(summary.get("commands_failed"), 0),
    }
    normalized["failure_report"] = {
        "root_causes": _string_list(failure_report.get("root_causes")),
        "failed_commands": _string_list(failure_report.get("failed_commands")),
    }
    normalized["next_action"] = result.get("next_action") or (
        "await_user_approval" if qa_passed else "rerun_user_agents"
    )
    normalized["next_action_reason"] = result.get("next_action_reason") or (
        "QA checks passed."
        if qa_passed
        else "Functional QA failed; regenerate coder outputs with failure context."
    )
    return normalized


# ── Workflow pipeline ──────────────────────────────────────────────
async def _run_pipeline(job_id: str, req: JobCreateReq):
    """
    Implements workflow:
    planning -> user approval loop
    -> task coordinator -> conflict analyst loop
    -> user coding agents -> merge loop-back-to-coordinator on failure
    -> QA loop-back-to-coders on failure
    -> final user approval (reject sends back to planning)
    """
    job = _jobs[job_id]
    plan_event = _plan_events[job_id]
    result_event = _result_events[job_id]

    try:
        while True:
            # ==========================================
            # PHASE 1: PLANNING + APPROVAL LOOP
            # ==========================================
            while True:
                job["planning_round"] += 1
                job["status"] = "planning"
                _set_agent_state(job, "planner", "running")
                _set_all_non_planner_idle(job)

                planning_feedback = (
                    job.get("plan_feedback")
                    or job["workflow_context"].get("replan_reason")
                    or ""
                )
                revision_source = "none"
                if planning_feedback:
                    coordinator_source = (
                        (job["workflow_context"].get("coordinator_feedback") or {}).get("source")
                        or ""
                    )
                    revision_source = (
                        "final_output_rejection"
                        if coordinator_source == "final_rejection"
                        else "plan_rejection"
                    )
                if planning_feedback:
                    _log(job, f"🧠 Planning Agent refining with feedback: '{planning_feedback[:80]}'")
                else:
                    _log(job, f"🧠 Planning Agent creating roadmap for goal: {req.goal[:80]}...")

                await _workflow_sleep(req, 1.5)
                job["plan"] = await _run_planning_agent(
                    req,
                    job["planning_round"],
                    planning_feedback,
                    revision_source,
                )
                _set_agent_state(job, "planner", "done")
                _log(job, "✓ Plan generated and ready for human approval.")

                job["status"] = "awaiting_plan_approval"
                _log(job, "⏳ Waiting for human plan approval...")
                job["plan_approved"] = None
                plan_event.clear()
                await plan_event.wait()

                if job.get("plan_approved"):
                    _log(job, "✅ Plan approved. Entering task coordination.")
                    break

                rejection_feedback = job.get("plan_feedback") or "No feedback provided."
                job["workflow_context"]["replan_reason"] = rejection_feedback
                _log(job, "❌ Plan rejected. Looping back to Planning Agent.")

            # Clear stale artifacts once a plan is approved
            job["task_distribution"] = None
            job["conflict_report"] = None
            job["user_agent_outputs"] = []
            job["merge_result"] = None
            job["qa_result"] = None
            job["workflow_context"]["coordinator_feedback"] = None
            job["workflow_context"]["execution_feedback"] = None

            restart_planning = False

            # ==========================================
            # PHASE 2A: TASK COORDINATOR + CONFLICT LOOP
            # ==========================================
            while True:
                job["coordination_round"] += 1
                coordinator_context = job["workflow_context"].get("coordinator_feedback")

                job["status"] = "coordinating"
                _set_agent_state(job, "conflict_analyst", "idle")
                _set_agent_state(job, "task_coordinator", "running")

                if coordinator_context:
                    _log(
                        job,
                        "🎯 Task Coordinator rebalancing with context: "
                        f"{(coordinator_context.get('reason') or '')[:90]}",
                    )
                else:
                    _log(job, "🎯 Task Coordinator assigning plan tasks to available agents...")

                await _workflow_sleep(req, 1.2)
                job["task_distribution"] = await _run_task_coordinator_agent(
                    req,
                    job["coordination_round"],
                    coordinator_context,
                    job["plan"] or "",
                )
                _set_agent_state(job, "task_coordinator", "done")
                _log(job, "✓ Task coordination output generated.")

                job["status"] = "analyzing_conflicts"
                _set_agent_state(job, "conflict_analyst", "running")
                _log(job, "⚖️ Conflict Analysis Agent evaluating assignment overlap risk...")
                await _workflow_sleep(req, 1.0)

                job["conflict_report"] = await _run_conflict_analysis_agent(
                    req,
                    job["coordination_round"],
                    coordinator_context,
                    job["task_distribution"],
                    job["plan"] or "",
                )
                _set_agent_state(job, "conflict_analyst", "done")

                if job["conflict_report"]["threshold_breached"]:
                    score = job["conflict_report"]["overall_conflict_score"]
                    threshold = job["conflict_report"]["threshold_percent"]
                    job["workflow_context"]["coordinator_feedback"] = {
                        "source": "conflict_analysis",
                        "reason": f"Conflict score {score}% exceeded threshold {threshold}%.",
                        "conflict_report": job["conflict_report"],
                    }
                    _log(
                        job,
                        "❌ Conflict analysis failed threshold. Returning to Task Coordinator with failure context.",
                    )
                    continue

                _log(job, "✅ Conflict analysis passed. Proceeding to user code agents.")

                # ==========================================
                # PHASE 2B: USER AGENTS -> MERGE -> QA LOOP
                # ==========================================
                while True:
                    job["execution_round"] += 1
                    execution_context = job["workflow_context"].get("execution_feedback")

                    job["status"] = "coding"
                    _set_agent_state(job, "user_agents", "running")
                    if execution_context:
                        _log(
                            job,
                            "💻 User agents regenerating code with QA context: "
                            f"{(execution_context.get('reason') or '')[:90]}",
                        )
                    else:
                        _log(job, f"💻 Running {req.coder_count} user code agent(s) against task assignments...")

                    await _workflow_sleep(req, 2.0)
                    job["user_agent_outputs"] = await _run_coding_agents(
                        req,
                        job["execution_round"],
                        execution_context,
                        job["task_distribution"],
                        job["plan"] or "",
                    )
                    _set_agent_state(job, "user_agents", "done")
                    _log(job, "✓ User agent outputs collected.")

                    job["status"] = "merging"
                    _set_agent_state(job, "merge_agent", "running")
                    _log(job, "🔀 Merge Agent attempting combined merge...")
                    await _workflow_sleep(req, 1.2)

                    job["merge_result"] = await _run_merge_agent(
                        req,
                        job["execution_round"],
                        coordinator_context,
                        job["user_agent_outputs"],
                        job["task_distribution"],
                        job["plan"] or "",
                    )
                    _set_agent_state(job, "merge_agent", "done")

                    if not job["merge_result"]["mergeable"]:
                        job["workflow_context"]["coordinator_feedback"] = {
                            "source": "merge_failure",
                            "reason": job["merge_result"]["next_action_reason"],
                            "merge_result": job["merge_result"],
                        }
                        job["workflow_context"]["execution_feedback"] = None
                        _log(job, "❌ Merge failed. Returning to Task Coordinator with merge context.")
                        break

                    _log(job, "✅ Merge successful. Proceeding to QA.")

                    job["status"] = "verifying"
                    _set_agent_state(job, "qa_agent", "running")
                    _log(job, "🧪 QA Agent running generated solution checks...")
                    await _workflow_sleep(req, 1.5)

                    job["qa_result"] = await _run_qa_agent(
                        req,
                        job["execution_round"],
                        execution_context,
                        job["merge_result"],
                        job["user_agent_outputs"],
                        job["plan"] or "",
                    )
                    _set_agent_state(job, "qa_agent", "done")

                    if not job["qa_result"]["qa_passed"]:
                        job["workflow_context"]["execution_feedback"] = {
                            "source": "qa_failure",
                            "reason": job["qa_result"]["next_action_reason"],
                            "failure_report": job["qa_result"]["failure_report"],
                        }
                        _log(
                            job,
                            "❌ QA failed. Looping back to user code agents with QA failure context.",
                        )
                        continue

                    _log(job, "✅ QA passed. Awaiting final user acceptance.")
                    job["status"] = "review_ready"
                    job["result_approved"] = None
                    result_event.clear()
                    await result_event.wait()

                    if job.get("result_approved"):
                        _log(job, "🎉 User accepted final output. Workflow complete.")
                        for key in (
                            "planner",
                            "task_coordinator",
                            "conflict_analyst",
                            "user_agents",
                            "merge_agent",
                            "qa_agent",
                        ):
                            _set_agent_state(job, key, "done")
                        job["status"] = "done"
                        return

                    rejection_feedback = (
                        job.get("result_feedback")
                        or "User requested a different overall solution direction."
                    )
                    job["plan_feedback"] = rejection_feedback
                    job["workflow_context"]["replan_reason"] = rejection_feedback
                    job["workflow_context"]["coordinator_feedback"] = {
                        "source": "final_rejection",
                        "reason": rejection_feedback,
                    }
                    job["workflow_context"]["execution_feedback"] = None
                    _log(job, "❌ User rejected final output. Returning to planning stage.")
                    restart_planning = True
                    break

                if restart_planning:
                    _set_all_non_planner_idle(job)
                    break
                # Merge failure route: loop task coordinator again

            if restart_planning:
                continue

    except Exception as e:
        job["status"] = "failed"
        _log(job, f"☠️ Pipeline critical error: {str(e)}")
        for agent in job["agent_states"]:
            if job["agent_states"][agent] == "running":
                job["agent_states"][agent] = "error"
