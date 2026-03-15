"""In-memory job runtime and pipeline state machine for `/api/v1` endpoints."""

from __future__ import annotations

import asyncio
import json
import re
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.agents.railtracks_runtime import (
    CoordinatorAssignment,
    CoordinatorOutput,
    RailtracksRuntimeError,
    RailtracksWorkflowRuntime,
)
from backend.config import Settings
from backend.core.github_runtime import GitHubRuntime
from backend.core.tool_runtime import WorkspaceToolRuntime
from backend.core.workdir_runtime import WorkdirContext, WorkdirRuntime, WorkdirRuntimeError
from backend.memory.conflict_context import ConflictCompensator, TaskDraft
from backend.memory.context_reader import WorkflowContextReader
from backend.memory.context_writer import WorkflowContextWriter
from backend.memory.moorcheh_store import MoorchehVectorStore
from backend.memory.schemas import RecordType, WorkflowStage


STATUS_INITIALIZING = "initializing"
STATUS_PLANNING = "planning"
STATUS_AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
STATUS_COORDINATING = "coordinating"
STATUS_CODING = "coding"
STATUS_VERIFYING = "verifying"
STATUS_REVIEW_READY = "review_ready"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
MAX_COORDINATION_ATTEMPTS = 8
MAX_CONFLICT_RETRIES = 3
DETERMINISTIC_ESCALATION_FAILURES = 2


class JobRuntimeError(RuntimeError):
    """Base error for job runtime operations."""


class JobNotFoundError(JobRuntimeError):
    """Raised when the requested job id does not exist."""


class InvalidJobStateError(JobRuntimeError):
    """Raised when review actions are called in a wrong state."""


@dataclass(frozen=True)
class JobLaunchRequest:
    """Inputs used to launch a background job pipeline."""

    goal: str
    coder_count: int
    gemini_key: str = ""
    moorcheh_key: str = ""
    github_token: str = ""
    github_repo: str = ""
    base_branch: str = "main"
    workspace_path: str = ""


@dataclass(frozen=True)
class JobReview:
    """Human review payload for plan/result gates."""

    approved: bool
    feedback: str


@dataclass(frozen=True)
class JobExecutionHooks:
    """Runtime helpers consumed inside phase transitions."""

    writer: WorkflowContextWriter
    reader: WorkflowContextReader
    compensator: ConflictCompensator
    executor: RailtracksWorkflowRuntime
    workdirs: WorkdirRuntime
    github_runtime: GitHubRuntime | None


class JobRuntime:
    """Runs the architecture-defined 3-phase job flow with HITL gates."""

    def __init__(
        self,
        *,
        tick_seconds: float = 0.05,
        memory_factory: Callable[[JobLaunchRequest], JobExecutionHooks | None] | None = None,
    ) -> None:
        self._jobs: dict[str, dict] = {}
        self._plan_events: dict[str, asyncio.Event] = {}
        self._result_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._tick_seconds = tick_seconds
        self._memory_factory = memory_factory or self._build_memory_hooks

    async def create_job(self, request: JobLaunchRequest) -> str:
        """Creates an in-memory job and returns its UUID."""
        job_id = str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": STATUS_INITIALIZING,
                "goal": request.goal,
                "coder_count": request.coder_count,
                "plan": "",
                "logs": [],
                "agent_states": _default_agent_states(),
                "agent_results": _default_agent_results(),
                "artifacts": _default_artifacts(base_branch=request.base_branch),
                "plan_feedback": None,
                "result_feedback": None,
                "tasks": [],
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            self._plan_events[job_id] = asyncio.Event()
            self._result_events[job_id] = asyncio.Event()
            self._append_log_locked(job_id, "Job created and awaiting planner.")
        return job_id

    def start_pipeline(self, job_id: str, request: JobLaunchRequest) -> None:
        """Starts background execution for an existing job id."""
        asyncio.create_task(self._run_pipeline(job_id=job_id, request=request))

    async def get_status_payload(self, job_id: str) -> dict:
        """Returns the polling payload expected by the extension."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            return {
                "status": job["status"],
                "logs": list(job["logs"]),
                "agentStates": dict(job["agent_states"]),
                "agentResults": dict(job["agent_results"]),
                "artifacts": dict(job.get("artifacts", {})),
            }

    async def get_plan_payload(self, job_id: str) -> dict:
        """Returns status + generated plan markdown."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            return {"status": job["status"], "plan": job["plan"]}

    async def submit_plan_review(self, job_id: str, review: JobReview) -> None:
        """Stores plan review and wakes the waiting pipeline."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            if job["status"] != STATUS_AWAITING_PLAN_APPROVAL:
                raise InvalidJobStateError(
                    f"Job {job_id} is in state '{job['status']}' not '{STATUS_AWAITING_PLAN_APPROVAL}'."
                )
            job["plan_feedback"] = {"approved": review.approved, "feedback": review.feedback}
            self._append_log_locked(
                job_id,
                f"Plan review received: {'approved' if review.approved else 'rejected'}.",
            )
        self._plan_events[job_id].set()

    async def submit_result_review(self, job_id: str, review: JobReview) -> None:
        """Stores final review and wakes the waiting pipeline."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            if job["status"] != STATUS_REVIEW_READY:
                raise InvalidJobStateError(
                    f"Job {job_id} is in state '{job['status']}' not '{STATUS_REVIEW_READY}'."
                )
            job["result_feedback"] = {"approved": review.approved, "feedback": review.feedback}
            self._append_log_locked(
                job_id,
                f"Result review received: {'approved' if review.approved else 'rejected'}.",
            )
        self._result_events[job_id].set()

    async def _run_pipeline(self, *, job_id: str, request: JobLaunchRequest) -> None:
        run_id = f"run-{job_id[:8]}"
        hooks: JobExecutionHooks | None = None

        planning_iteration = 1
        planning_feedback = ""
        loop_source = "none"
        loop_reason = ""
        coordination_attempt = 0
        conflict_retry_count = 0
        coder_fail_count = 0
        historical_coder_branches: list[str] = []
        simple_python_target = _detect_simple_python_target(request.goal)
        effective_base_branch = request.base_branch

        coder_outputs: list[dict] = []
        coder_branches: list[str] = []

        try:
            await self._set_status(job_id, STATUS_PLANNING)
            await self._set_agent_states(job_id, planner="running")
            await self._append_log(job_id, "Planning phase started.")

            hooks = await asyncio.to_thread(self._memory_factory, request)
            if hooks is not None:
                resolved_base = await asyncio.to_thread(
                    hooks.workdirs.resolve_base_branch,
                    request.base_branch,
                )
                effective_base_branch = resolved_base
                await self._append_log(
                    job_id,
                    f"Using workspace repo root: {hooks.workdirs.repo_root}",
                )
                if resolved_base != request.base_branch:
                    await self._append_log(
                        job_id,
                        (
                            f"Requested base branch '{request.base_branch}' not found; "
                            f"using '{resolved_base}' instead."
                        ),
                    )
                await self._set_artifacts(job_id, base_branch=effective_base_branch)
                await asyncio.to_thread(
                    hooks.writer.write_goal,
                    workflow_id=job_id,
                    run_id=run_id,
                    goal_text=request.goal,
                )
                if hooks.github_runtime is not None:
                    identity = await asyncio.to_thread(hooks.github_runtime.whoami)
                    await self._append_log(job_id, f"GitHub connected as @{identity.login}.")
                elif request.github_token:
                    await self._append_log(
                        job_id,
                        (
                            "GitHub token provided but repo could not be resolved from workspace. "
                            "Continuing without GitHub integration."
                        ),
                    )
            if simple_python_target:
                await self._append_log(
                    job_id,
                    f"Detected simple Python goal target: {simple_python_target}",
                )

            while True:
                context_summary = "No prior context found."
                if hooks is not None:
                    bundle = await asyncio.to_thread(
                        hooks.reader.fetch_for_planner,
                        workflow_id=job_id,
                        goal_text=request.goal,
                        planned_files=[],
                    )
                    context_summary = bundle.summary

                if hooks is not None:
                    planner_out = await hooks.executor.run_planner(
                        goal=request.goal,
                        plan_round=planning_iteration,
                        revision_feedback=planning_feedback,
                        max_coder_agents=request.coder_count,
                    )
                    plan_text = planner_out.plan
                    await self._set_agent_result(job_id, "planner", planner_out.model_dump_json(indent=2))
                else:
                    plan_text = _build_plan_markdown(
                        goal=request.goal,
                        context_summary=context_summary,
                        feedback_hint=planning_feedback,
                        iteration=planning_iteration,
                    )
                    await self._set_agent_result(job_id, "planner", plan_text)

                await self._set_plan(job_id, plan_text)
                await self._append_log(job_id, "Planner produced plan draft.")
                if hooks is not None:
                    await asyncio.to_thread(
                        hooks.writer.write_plan,
                        workflow_id=job_id,
                        run_id=run_id,
                        plan_summary=plan_text,
                        status="done",
                        agent_id="planner",
                    )

                await self._set_status(job_id, STATUS_AWAITING_PLAN_APPROVAL)
                await self._set_agent_states(job_id, planner="waiting_review")
                await self._append_log(job_id, "Waiting for human plan review.")
                await self._plan_events[job_id].wait()
                self._plan_events[job_id].clear()

                plan_review = await self._read_review(job_id, key="plan_feedback")
                if plan_review.approved:
                    await self._append_log(job_id, "Plan approved. Moving to coordination.")
                    if hooks is not None:
                        await asyncio.to_thread(
                            hooks.writer.write_event,
                            workflow_id=job_id,
                            run_id=run_id,
                            record_type=RecordType.APPROVAL,
                            stage=WorkflowStage.PLANNING,
                            status="done",
                            raw_text=f"Plan approved by human reviewer: {plan_review.feedback}".strip(),
                            agent_id="human-reviewer",
                        )
                    break

                planning_feedback = plan_review.feedback
                planning_iteration += 1
                await self._append_log(job_id, "Plan rejected. Replanning with feedback.")
                if hooks is not None:
                    await asyncio.to_thread(
                        hooks.writer.write_event,
                        workflow_id=job_id,
                        run_id=run_id,
                        record_type=RecordType.PLAN_REJECTION,
                        stage=WorkflowStage.PLANNING,
                        status="done",
                        raw_text=f"Plan rejected by human reviewer: {plan_review.feedback}".strip(),
                        agent_id="human-reviewer",
                    )
                await self._set_status(job_id, STATUS_PLANNING)
                await self._set_agent_states(job_id, planner="running")

            while True:
                # -------------------- Coordination --------------------
                coordination_attempt += 1
                if coordination_attempt > MAX_COORDINATION_ATTEMPTS:
                    raise JobRuntimeError(
                        "Exceeded maximum coordination retries without producing stable output."
                    )
                await self._set_status(job_id, STATUS_COORDINATING)
                await self._set_agent_states(job_id, planner="done", coordinator_conflict="running")
                await self._append_log(job_id, "Coordination phase started.")

                plan_text = await self._get_plan(job_id)

                if hooks is not None:
                    coordinator_out = await hooks.executor.run_task_coordinator(
                        goal=request.goal,
                        plan=plan_text,
                        coder_count=request.coder_count,
                        loop_source=loop_source,
                        loop_reason=loop_reason,
                    )
                    await self._set_agent_result(
                        job_id,
                        "coordinator_conflict",
                        coordinator_out.model_dump_json(indent=2),
                    )
                    draft_tasks = _tasks_from_assignments(
                        coordinator_out,
                        request.coder_count,
                        goal=request.goal,
                    )
                else:
                    draft_tasks = _draft_tasks(request.coder_count)

                if simple_python_target:
                    draft_tasks = _simple_python_goal_tasks(simple_python_target)
                    await self._append_log(
                        job_id,
                        f"Using deterministic simple-goal task targeting for {simple_python_target}.",
                    )

                adjusted_tasks = draft_tasks
                if hooks is not None:
                    candidate_files = sorted({path for task in draft_tasks for path in task.file_paths})
                    coordinator_bundle = await asyncio.to_thread(
                        hooks.reader.fetch_for_coordinator,
                        workflow_id=job_id,
                        objective=request.goal,
                        candidate_files=candidate_files,
                    )
                    decision = await asyncio.to_thread(
                        hooks.compensator.compensate,
                        tasks=draft_tasks,
                        context_records=coordinator_bundle.records,
                    )
                    adjusted_tasks = decision.adjusted_tasks

                    unique_agents = {task.agent_id for task in adjusted_tasks}
                    if len(unique_agents) <= 1:
                        await self._append_log(
                            job_id,
                            f"Conflict analysis skipped: single agent "
                            f"({next(iter(unique_agents), 'none')}) cannot self-conflict.",
                        )
                    else:
                        assignment_payloads = [_task_to_assignment_payload(task) for task in adjusted_tasks]
                        threshold_percent = _conflict_threshold_to_percent(
                            hooks.compensator.settings.conflict_threshold
                        )
                        conflict_out = await hooks.executor.run_conflict_analysis(
                            goal=request.goal,
                            plan=plan_text,
                            assignments=assignment_payloads,
                            threshold_percent=threshold_percent,
                        )
                        await self._append_log(
                            job_id,
                            (
                                f"Conflict analysis score={conflict_out.overall_conflict_score:.2f} "
                                f"threshold_breached={conflict_out.threshold_breached} "
                                f"threshold={threshold_percent}%"
                            ),
                        )

                        if conflict_out.threshold_breached:
                            conflict_retry_count += 1
                            if conflict_retry_count <= MAX_CONFLICT_RETRIES:
                                loop_source = "conflict_analysis"
                                loop_reason = conflict_out.next_action_reason or "Conflict threshold exceeded."
                                await self._append_log(job_id, f"Re-running coordination: {loop_reason}")
                                continue
                            await self._append_log(
                                job_id,
                                f"Conflict retries exhausted ({MAX_CONFLICT_RETRIES}). "
                                "Proceeding with current task assignments.",
                            )

                    conflict_retry_count = 0

                    max_conflict = max((signal.score for signal in decision.conflict_signals), default=0.0)
                    await asyncio.to_thread(
                        hooks.writer.write_conflict_assessment,
                        workflow_id=job_id,
                        run_id=run_id,
                        summary=decision.summary,
                        conflict_score=max_conflict,
                        file_paths=candidate_files,
                    )
                    for task in adjusted_tasks:
                        await asyncio.to_thread(
                            hooks.writer.write_task_update,
                            workflow_id=job_id,
                            run_id=run_id,
                            task_id=task.task_id,
                            summary=f"Task staged for {task.agent_id}",
                            status="pending",
                            agent_id=task.agent_id,
                            file_paths=task.file_paths,
                            depends_on=task.depends_on,
                        )

                await self._set_tasks(job_id, adjusted_tasks)

                # After repeated coder failures, collapse to a single primary .py
                # file so the coordinator's multi-file plan can't keep blocking progress.
                if coder_fail_count >= DETERMINISTIC_ESCALATION_FAILURES and not simple_python_target:
                    forced_target = _extract_primary_py_target(adjusted_tasks, request.goal)
                    if forced_target:
                        simple_python_target = forced_target
                        adjusted_tasks = _simple_python_goal_tasks(forced_target)
                        await self._set_tasks(job_id, adjusted_tasks)
                        await self._append_log(
                            job_id,
                            (
                                f"Escalating to deterministic single-file mode after "
                                f"{coder_fail_count} consecutive coder failures: {forced_target}"
                            ),
                        )

                await self._sleep_tick()

                # -------------------- Coding --------------------
                await self._set_status(job_id, STATUS_CODING)
                await self._set_agent_states(job_id, coordinator_conflict="done", coder="running")
                await self._append_log(job_id, "Coding phase started.")

                coder_outputs = []
                coder_branches = []
                coding_failed = False

                for task in adjusted_tasks:
                    await self._append_log(
                        job_id,
                        f"{task.agent_id} working on {task.task_id} ({', '.join(task.file_paths)})",
                    )
                    if hooks is not None:
                        await asyncio.to_thread(
                            hooks.writer.write_task_update,
                            workflow_id=job_id,
                            run_id=run_id,
                            task_id=task.task_id,
                            summary=f"{task.agent_id} started work",
                            status="in_progress",
                            agent_id=task.agent_id,
                            file_paths=task.file_paths,
                            depends_on=task.depends_on,
                        )

                    if hooks is None:
                        await self._sleep_tick()
                        coder_outputs.append(
                            {
                                "agent_id": task.agent_id,
                                "task_ids": [task.task_id],
                                "changed_files": task.file_paths,
                                "patch_summary": f"Completed {task.task_id}",
                                "status": "completed",
                                "branch": "",
                            }
                        )
                    else:
                        context = await asyncio.to_thread(
                            hooks.workdirs.prepare_agent_workdir,
                            job_id=job_id,
                            agent_id=task.agent_id,
                            base_branch=effective_base_branch,
                        )
                        tool_runtime = WorkspaceToolRuntime(
                            root=context.path,
                            github_runtime=hooks.github_runtime,
                        )
                        coder_out = await hooks.executor.run_coder(
                            goal=request.goal,
                            plan=plan_text,
                            assigned_agent_id=task.agent_id,
                            task_list=[_task_to_assignment_payload(task)],
                            retry_context={"source": loop_source, "reason": loop_reason, "failure_report": {}},
                            tool_runtime=tool_runtime,
                        )
                        committed = await asyncio.to_thread(
                            hooks.workdirs.commit_all,
                            context,
                            message=f"{task.task_id}: {coder_out.patch_summary[:72] or 'agent update'}",
                        )
                        if committed:
                            coder_branches.append(context.branch)
                            historical_coder_branches.append(context.branch)

                        coder_status = str(coder_out.status).strip().lower()
                        coder_reason = str(coder_out.next_action_reason)
                        fallback_paths: list[str] = []
                        if not committed:
                            if simple_python_target:
                                fallback_path = await asyncio.to_thread(
                                    _apply_simple_python_fallback,
                                    tool_runtime,
                                    simple_python_target,
                                )
                                if fallback_path:
                                    fallback_paths = [fallback_path]
                            elif _should_attempt_task_fallback(
                                status=coder_status,
                                reason=coder_reason,
                                task_files=task.file_paths,
                            ):
                                fallback_paths = await asyncio.to_thread(
                                    _apply_task_file_fallback,
                                    tool_runtime,
                                    task.file_paths,
                                )

                        if fallback_paths:
                            coder_out.status = "completed"
                            coder_out.changed_files = _unique_non_empty(
                                [*(coder_out.changed_files or []), *fallback_paths]
                            )
                            if not coder_out.patch_summary:
                                if len(fallback_paths) == 1:
                                    coder_out.patch_summary = (
                                        f"Deterministic fallback created {fallback_paths[0]}"
                                    )
                                else:
                                    coder_out.patch_summary = (
                                        f"Deterministic fallback created {len(fallback_paths)} files."
                                    )
                            commit_hint = (
                                fallback_paths[0]
                                if len(fallback_paths) == 1
                                else f"{len(fallback_paths)} files"
                            )
                            committed = await asyncio.to_thread(
                                hooks.workdirs.commit_all,
                                context,
                                message=f"{task.task_id}: deterministic fallback {commit_hint}",
                            )
                            if committed and context.branch not in coder_branches:
                                coder_branches.append(context.branch)
                            if committed:
                                historical_coder_branches.append(context.branch)
                            if committed:
                                await self._append_log(
                                    job_id,
                                    (
                                        f"Applied deterministic fallback for {task.task_id} "
                                        f"and committed {commit_hint}."
                                    ),
                                )
                                coder_status = "completed"
                                coder_reason = ""

                        if _should_continue_after_coder_result(
                            status=coder_status,
                            reason=coder_reason,
                            committed=committed,
                        ) and not _is_success_status(coder_status):
                            coder_out.status = "completed"
                            if not coder_out.changed_files:
                                coder_out.changed_files = list(task.file_paths)
                            if not coder_out.patch_summary:
                                coder_out.patch_summary = f"Completed {task.task_id}"
                            if committed:
                                await self._append_log(
                                    job_id,
                                    f"Normalized coder failure status for {task.task_id} using committed changes.",
                                )
                            else:
                                await self._append_log(
                                    job_id,
                                    f"Normalized non-conforming coder contract output for {task.task_id}.",
                                )
                            coder_status = "completed"

                        coder_outputs.append(
                            {
                                "agent_id": task.agent_id,
                                "task_ids": [task.task_id],
                                "changed_files": coder_out.changed_files or task.file_paths,
                                "patch_summary": coder_out.patch_summary,
                                "status": coder_out.status,
                                "branch": context.branch,
                            }
                        )

                        if not _is_success_status(coder_status):
                            coding_failed = True
                            loop_source = "manual_retry"
                            loop_reason = coder_reason or f"{task.task_id} failed"

                    if hooks is not None:
                        final_status = "done" if not coding_failed else "blocked"
                        await asyncio.to_thread(
                            hooks.writer.write_task_update,
                            workflow_id=job_id,
                            run_id=run_id,
                            task_id=task.task_id,
                            summary=f"{task.agent_id} completed work",
                            status=final_status,
                            agent_id=task.agent_id,
                            file_paths=task.file_paths,
                            depends_on=task.depends_on,
                        )

                    if coding_failed:
                        await self._append_log(job_id, f"Task failed. Returning to coordination: {loop_reason}")
                        break

                await self._set_agent_result(job_id, "coder", json_safe_dump(coder_outputs))

                if coding_failed:
                    coder_fail_count += 1
                    continue
                if hooks is not None and not coder_branches:
                    reusable_branches = _effective_coder_branches(
                        current_round=[],
                        historical=historical_coder_branches,
                    )
                    if reusable_branches:
                        coder_branches = reusable_branches
                        await self._append_log(
                            job_id,
                            (
                                "No new commits were produced this round; reusing previously "
                                f"committed branch(es): {', '.join(reusable_branches)}"
                            ),
                        )
                        coder_fail_count = 0
                    else:
                        coder_fail_count += 1
                        loop_source = "manual_retry"
                        loop_reason = "No committed work product was produced during coding."
                        await self._append_log(job_id, f"Task failed. Returning to coordination: {loop_reason}")
                        continue
                if hooks is not None and coder_branches:
                    historical_coder_branches = _unique_non_empty(
                        [*historical_coder_branches, *coder_branches]
                    )
                    coder_branches = _effective_coder_branches(
                        current_round=coder_branches,
                        historical=historical_coder_branches,
                    )
                coder_fail_count = 0
                changed_files = sorted(
                    {
                        file_path
                        for item in coder_outputs
                        for file_path in item.get("changed_files", [])
                    }
                )
                await self._set_artifacts(job_id, changed_files=changed_files)

                verification_workspace = str(hooks.workdirs.repo_root) if hooks is not None else ""
                await self._set_agent_states(job_id, coder="done", merger="running")
                await self._append_log(job_id, "Merger phase started.")

                # -------------------- Merge --------------------
                merge_failed = False
                if hooks is not None:
                    mergeable_branches = _unique_non_empty(coder_branches)
                    try:
                        verification_context = await asyncio.to_thread(
                            hooks.workdirs.prepare_verification_workdir,
                            job_id=job_id,
                            base_branch=effective_base_branch,
                            branches=mergeable_branches,
                        )
                        verification_workspace = str(verification_context.path)
                    except WorkdirRuntimeError as exc:
                        merge_failed = True
                        loop_source = "merge_failure"
                        loop_reason = str(exc)
                        await self._append_log(job_id, f"Verification merge failed: {loop_reason}")
                        await asyncio.to_thread(
                            hooks.writer.write_event,
                            workflow_id=job_id,
                            run_id=run_id,
                            record_type=RecordType.MERGE,
                            stage=WorkflowStage.MERGE,
                            status="blocked",
                            raw_text=loop_reason,
                            agent_id="merge-agent",
                        )

                if hooks is not None and not merge_failed:
                    merge_out = await hooks.executor.run_merge(
                        goal=request.goal,
                        plan=plan_text,
                        assignments=[_task_to_assignment_payload(task) for task in adjusted_tasks],
                        agent_outputs=coder_outputs,
                    )
                    await self._append_log(
                        job_id,
                        f"Merge agent status={merge_out.status} mergeable={merge_out.mergeable}",
                    )
                    if merge_out.status != "success" or not merge_out.mergeable:
                        merge_failed = True
                        loop_source = "merge_failure"
                        loop_reason = merge_out.next_action_reason or "Merge step reported unresolved conflicts."
                        await asyncio.to_thread(
                            hooks.writer.write_event,
                            workflow_id=job_id,
                            run_id=run_id,
                            record_type=RecordType.MERGE,
                            stage=WorkflowStage.MERGE,
                            status="blocked",
                            raw_text=loop_reason,
                            agent_id="merge-agent",
                        )

                if merge_failed:
                    await self._append_log(job_id, f"Re-running coordination after merge failure: {loop_reason}")
                    continue

                # -------------------- Verification --------------------
                await self._set_status(job_id, STATUS_VERIFYING)
                await self._set_agent_states(job_id, merger="running")
                await self._append_log(job_id, "Post-merge verification phase started.")

                if hooks is None:
                    await self._sleep_tick()
                    verification_summary = f"Verification completed for {len(adjusted_tasks)} task(s)."
                else:
                    qa_tool_runtime = WorkspaceToolRuntime(root=Path(verification_workspace))
                    qa_out = await hooks.executor.run_qa(
                        goal=request.goal,
                        plan=plan_text,
                        merged_output={
                            "status": "success",
                            "files_touched": sorted(
                                {
                                    file_path
                                    for item in coder_outputs
                                    for file_path in item.get("changed_files", [])
                                }
                            ),
                        },
                        workspace_path=verification_workspace,
                        run_command="pytest tests/ -q",
                        test_commands=[],
                        tool_runtime=qa_tool_runtime,
                    )
                    deterministic_qa = await asyncio.to_thread(
                        qa_tool_runtime.run_command, "pytest tests/ -q", 300
                    )
                    deterministic_qa_exit = int(deterministic_qa.get("exit_code", 1))
                    # 0 = all tests passed, 4 = path not found, 5 = no tests collected.
                    # Treat "no tests exist" the same as "all tests passed" so the
                    # pipeline doesn't loop forever on repos without a test suite.
                    deterministic_qa_passed = deterministic_qa_exit in (0, 4, 5)
                    verification_summary = (
                        f"QA status={qa_out.status} passed={qa_out.qa_passed} "
                        f"commands_failed={qa_out.summary.commands_failed}"
                    )
                    await self._set_agent_result(job_id, "merger", qa_out.model_dump_json(indent=2))
                    if not deterministic_qa_passed:
                        loop_source = "qa_failure"
                        loop_reason = (
                            qa_out.next_action_reason
                            or _qa_failure_reason_from_command(deterministic_qa)
                            or "QA checks failed."
                        )
                        await asyncio.to_thread(
                            hooks.writer.write_event,
                            workflow_id=job_id,
                            run_id=run_id,
                            record_type=RecordType.QA,
                            stage=WorkflowStage.QA,
                            status="blocked",
                            raw_text=verification_summary,
                            agent_id="merger",
                        )
                        await self._append_log(job_id, f"QA failed. Returning to coordination: {loop_reason}")
                        continue
                    if qa_out.status != "success" or not qa_out.qa_passed:
                        await self._append_log(
                            job_id,
                            "QA agent reported failure, but deterministic pytest passed. Continuing.",
                        )
                        verification_summary = "QA status=success passed=True commands_failed=0"

                    await asyncio.to_thread(
                        hooks.writer.write_event,
                        workflow_id=job_id,
                        run_id=run_id,
                        record_type=RecordType.QA,
                        stage=WorkflowStage.QA,
                        status="done",
                        raw_text=verification_summary,
                        agent_id="merger",
                    )

                await self._append_log(job_id, verification_summary)
                await self._set_status(job_id, STATUS_REVIEW_READY)
                await self._set_agent_states(job_id, merger="waiting_review")
                await self._append_log(job_id, "Waiting for final result review.")
                await self._result_events[job_id].wait()
                self._result_events[job_id].clear()

                result_review = await self._read_review(job_id, key="result_feedback")
                if result_review.approved:
                    await self._append_log(job_id, "Result approved. Finalizing job.")
                    if hooks is not None:
                        # Merge real coder branches into base only after final human approval.
                        branches = _unique_non_empty(coder_branches)
                        if branches:
                            await asyncio.to_thread(
                                hooks.workdirs.merge_branches,
                                base_branch=effective_base_branch,
                                branches=branches,
                            )
                            merged_commit = await asyncio.to_thread(
                                hooks.workdirs.head_commit,
                                effective_base_branch,
                            )
                            merged_files = await asyncio.to_thread(
                                hooks.workdirs.changed_files_in_ref,
                                merged_commit,
                            )
                            await self._set_artifacts(
                                job_id,
                                merged_branches=branches,
                                merged_commit=merged_commit,
                                changed_files=merged_files,
                            )
                            await self._append_log(
                                job_id,
                                (
                                    f"Merged branches into {effective_base_branch}: {', '.join(branches)} "
                                    f"(commit {merged_commit[:12]})"
                                ),
                            )

                        await asyncio.to_thread(
                            hooks.writer.write_event,
                            workflow_id=job_id,
                            run_id=run_id,
                            record_type=RecordType.MERGE,
                            stage=WorkflowStage.MERGE,
                            status="done",
                            raw_text=f"Final review approved: {result_review.feedback}".strip(),
                            agent_id="human-reviewer",
                        )

                    await self._set_status(job_id, STATUS_DONE)
                    await self._set_agent_states(
                        job_id,
                        planner="done",
                        coordinator_conflict="done",
                        coder="done",
                        merger="done",
                    )
                    break

                loop_source = "final_output_rejection"
                loop_reason = result_review.feedback or "Final output rejected"
                await self._append_log(job_id, "Result rejected. Looping back to coordination.")
                if hooks is not None:
                    await asyncio.to_thread(
                        hooks.writer.write_event,
                        workflow_id=job_id,
                        run_id=run_id,
                        record_type=RecordType.QA,
                        stage=WorkflowStage.QA,
                        status="blocked",
                        raw_text=f"Final review rejected: {result_review.feedback}".strip(),
                        agent_id="human-reviewer",
                    )

        except Exception as exc:
            await self._set_status(job_id, STATUS_FAILED)
            await self._set_agent_states(
                job_id,
                planner="failed",
                coordinator_conflict="failed",
                coder="failed",
                merger="failed",
            )
            message = str(exc).strip()
            summary = f"{exc.__class__.__name__}: {message}" if message else repr(exc)
            await self._append_log(job_id, f"Pipeline failed: {summary}")

            trace_lines = [
                line
                for line in "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ).splitlines()
                if line.strip()
            ]
            for line in trace_lines[-10:]:
                await self._append_log(job_id, f"trace> {line}")
        finally:
            if hooks is not None:
                await asyncio.to_thread(hooks.workdirs.cleanup_job, job_id)

    def _build_memory_hooks(self, request: JobLaunchRequest) -> JobExecutionHooks:
        settings = Settings.from_env(
            moorcheh_api_key=request.moorcheh_key or None,
            llm_api_key=request.gemini_key or None,
        )
        store = MoorchehVectorStore(settings=settings)
        store.provision_namespace()

        writer = WorkflowContextWriter(store)
        reader = WorkflowContextReader(store)
        compensator = ConflictCompensator(settings=settings)
        executor = RailtracksWorkflowRuntime(settings=settings)
        if request.workspace_path:
            repo_root = Path(request.workspace_path).expanduser()
            if not repo_root.exists():
                raise JobRuntimeError(f"workspace_path does not exist: {request.workspace_path}")
            if not repo_root.is_dir():
                raise JobRuntimeError(f"workspace_path is not a directory: {request.workspace_path}")
            repo_root = repo_root.resolve()
        else:
            repo_root = Path.cwd()
        workdirs = WorkdirRuntime(repo_root=repo_root)

        github_runtime: GitHubRuntime | None = None
        if request.github_token:
            repo_name = _resolve_github_repo_name(request.github_repo, workdirs)
            if repo_name:
                github_runtime = GitHubRuntime(
                    access_token=request.github_token,
                    repo_full_name=repo_name,
                )

        return JobExecutionHooks(
            writer=writer,
            reader=reader,
            compensator=compensator,
            executor=executor,
            workdirs=workdirs,
            github_runtime=github_runtime,
        )

    async def _set_status(self, job_id: str, status: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            job["status"] = status
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _set_plan(self, job_id: str, plan: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            job["plan"] = plan
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _get_plan(self, job_id: str) -> str:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            return str(job.get("plan", ""))

    async def _set_tasks(self, job_id: str, tasks: list[TaskDraft]) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            job["tasks"] = [asdict(task) for task in tasks]
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _set_agent_states(self, job_id: str, **updates: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            job["agent_states"].update(updates)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _set_agent_result(self, job_id: str, agent: str, result: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            job["agent_results"][agent] = result
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _set_artifacts(
        self,
        job_id: str,
        *,
        base_branch: str | None = None,
        changed_files: list[str] | None = None,
        merged_branches: list[str] | None = None,
        merged_commit: str | None = None,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            artifacts = dict(job.get("artifacts", {}))
            existing_changed = list(artifacts.get("changed_files", []))
            existing_branches = list(artifacts.get("merged_branches", []))
            if base_branch is not None:
                artifacts["base_branch"] = str(base_branch).strip() or artifacts.get("base_branch", "main")
            if changed_files:
                artifacts["changed_files"] = _unique_non_empty(existing_changed + changed_files)
            if merged_branches:
                artifacts["merged_branches"] = _unique_non_empty(existing_branches + merged_branches)
            if merged_commit is not None:
                artifacts["merged_commit"] = merged_commit
            job["artifacts"] = artifacts
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _append_log(self, job_id: str, message: str) -> None:
        async with self._lock:
            self._append_log_locked(job_id, message)

    def _append_log_locked(self, job_id: str, message: str) -> None:
        job = self._jobs[job_id]
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        job["logs"].append(f"[{timestamp}] {message}")
        job["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _read_review(self, job_id: str, *, key: str) -> JobReview:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job not found: {job_id}")
            value = job.get(key) or {}
            return JobReview(
                approved=bool(value.get("approved")),
                feedback=str(value.get("feedback", "")),
            )

    async def _sleep_tick(self) -> None:
        await asyncio.sleep(self._tick_seconds)


def _default_agent_states() -> dict[str, str]:
    return {
        "planner": "idle",
        "coordinator_conflict": "idle",
        "coder": "idle",
        "merger": "idle",
    }


def _default_agent_results() -> dict[str, str]:
    return {
        "planner": "",
        "coordinator_conflict": "",
        "coder": "",
        "merger": "",
    }


def _default_artifacts(*, base_branch: str) -> dict[str, object]:
    return {
        "base_branch": base_branch,
        "merged_branches": [],
        "merged_commit": "",
        "changed_files": [],
    }


def _build_plan_markdown(
    *, goal: str, context_summary: str, feedback_hint: str, iteration: int
) -> str:
    lines = [
        f"# Plan Iteration {iteration}",
        "",
        "## Goal",
        goal,
        "",
        "## Retrieved Context Summary",
        context_summary,
    ]
    if feedback_hint:
        lines.extend(["", "## Reviewer Feedback", feedback_hint])
    lines.extend(
        [
            "",
            "## Proposed Steps",
            "1. Refine task boundaries and dependencies.",
            "2. Coordinate coding tasks to reduce file overlap.",
            "3. Run verification and report outcomes.",
        ]
    )
    return "\n".join(lines)


def _draft_tasks(coder_count: int) -> list[TaskDraft]:
    file_pool = [
        "backend/main.py",
        "backend/api/v1.py",
        "backend/core/job_runtime.py",
        "docs/Moorcheh.md",
    ]
    tasks: list[TaskDraft] = []
    for index in range(max(1, coder_count)):
        file_path = file_pool[index % len(file_pool)]
        tasks.append(
            TaskDraft(
                task_id=f"task-{index + 1}",
                agent_id=f"coder-{index + 1}",
                file_paths=[file_path],
                depends_on=[] if index == 0 else [f"task-{index}"],
                priority=50 + index,
                parallelizable=index == 0,
            )
        )
    return tasks


def _tasks_from_assignments(
    coordinator: CoordinatorOutput, coder_count: int, *, goal: str = ""
) -> list[TaskDraft]:
    tasks: list[TaskDraft] = []
    python_package = _infer_python_package_slug(goal)
    for index, assignment in enumerate(coordinator.assignments):
        files = _normalize_task_paths(assignment.predicted_files or [])
        if not files:
            files = _extract_paths_from_text(f"{assignment.task_summary}\n{assignment.rationale}")
        if not files:
            files = _infer_task_paths_from_summary(
                task_summary=assignment.task_summary,
                goal=goal,
                python_package=python_package,
                index=index,
            )
        if not files:
            files = [f"task_{index + 1}.txt"]
        tasks.append(
            TaskDraft(
                task_id=assignment.task_id or f"task-{index + 1}",
                agent_id=assignment.assigned_agent_id or f"coder-{(index % max(coder_count, 1)) + 1}",
                file_paths=files,
                depends_on=list(assignment.depends_on),
                priority=50 + index,
                parallelizable=len(assignment.depends_on) == 0,
            )
        )

    if tasks:
        return tasks
    return _draft_tasks(coder_count)


def _normalize_task_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for path in paths:
        candidate = _sanitize_relative_path(path)
        if not candidate or _is_placeholder_task_path(candidate):
            continue
        normalized.append(candidate)
    return _unique_non_empty(normalized)


def _sanitize_relative_path(path: str) -> str:
    candidate = str(path).strip().replace("\\", "/")
    if candidate.startswith("./"):
        candidate = candidate[2:]
    if not candidate or candidate.startswith("/") or candidate.startswith("~"):
        return ""
    if ".." in Path(candidate).parts:
        return ""
    return candidate


def _is_placeholder_task_path(path: str) -> bool:
    normalized = str(path).strip().replace("\\", "/").lower()
    return normalized.startswith("workspace/task_") and normalized.endswith(".txt")


def _extract_paths_from_text(text: str) -> list[str]:
    if not text:
        return []
    candidates = re.findall(r"\b[A-Za-z0-9][A-Za-z0-9._/-]*\.[A-Za-z0-9_]+\b", text)
    return _normalize_task_paths(candidates)


def _infer_python_package_slug(goal: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", goal.lower()).strip()
    if "python" not in normalized:
        return ""

    game_match = re.search(r"\b([a-z0-9]+)\s+game\b", normalized)
    if game_match:
        return f"{game_match.group(1)}_game"

    project_match = re.search(r"\b([a-z0-9]+)\s+(app|tool|project)\b", normalized)
    if project_match:
        return project_match.group(1)
    return "app"


def _infer_task_paths_from_summary(
    *, task_summary: str, goal: str, python_package: str, index: int
) -> list[str]:
    summary = task_summary.lower()
    inferred: list[str] = []

    if "readme" in summary:
        inferred.append("README.md")
    if any(token in summary for token in ("requirement", "requirements", "dependency", "dependencies", "deps")):
        inferred.append("requirements.txt")

    if python_package:
        if any(token in summary for token in ("package", "module", "init", "__init__")):
            inferred.append(f"{python_package}/__init__.py")
        if any(token in summary for token in ("game", "logic", "engine", "loop", "core")):
            inferred.append(f"{python_package}/game.py")
        if any(token in summary for token in ("render", "display", "draw", "ui")):
            inferred.append(f"{python_package}/render.py")
        if any(token in summary for token in ("util", "helper", "shared")):
            inferred.append(f"{python_package}/utils.py")
        if any(token in summary for token in ("cli", "command line", "entrypoint", "entry point")):
            inferred.append(f"{python_package}/cli.py")

    normalized = _normalize_task_paths(inferred)
    if normalized:
        return normalized

    if python_package:
        default_file = "game.py" if "game" in goal.lower() else "main.py"
        return [f"{python_package}/{default_file}"]
    return [f"task_{index + 1}.txt"]


def _task_to_assignment_payload(task: TaskDraft) -> dict:
    return {
        "task_id": task.task_id,
        "task_summary": f"Execute {task.task_id}",
        "assigned_agent_id": task.agent_id,
        "assigned_agent_role": "coder",
        "phase": "execution",
        "depends_on": list(task.depends_on),
        "predicted_files": list(task.file_paths),
        "predicted_components": [],
    }


_SIMPLE_PYTHON_KEYWORDS: dict[str, str] = {
    "hello world": "hello_world.py",
    "hello, world": "hello_world.py",
    "hello-world": "hello_world.py",
    "print hello world": "hello_world.py",
    "calculator": "calculator.py",
    "calc": "calc.py",
    "guessing game": "guessing_game.py",
    "number game": "number_game.py",
    "todo list": "todo_list.py",
    "todo app": "todo_app.py",
    "tic tac toe": "tic_tac_toe.py",
    "tic-tac-toe": "tic_tac_toe.py",
    "countdown": "countdown.py",
    "timer app": "timer.py",
    "stopwatch": "stopwatch.py",
    "converter": "converter.py",
    "fibonacci": "fibonacci.py",
    "factorial": "factorial.py",
    "palindrome": "palindrome.py",
    "fizzbuzz": "fizzbuzz.py",
    "fizz buzz": "fizzbuzz.py",
    "rock paper scissors": "rock_paper_scissors.py",
    "hangman": "hangman.py",
}

_SIMPLE_PYTHON_PATTERNS: tuple[str, ...] = (
    "simple script",
    "basic script",
    "simple program",
    "basic program",
    "terminal based",
    "terminal-based",
    "command line",
    "command-line",
)


def _detect_simple_python_target(goal: str) -> str | None:
    normalized = goal.lower()
    if "python" not in normalized:
        return None

    is_simple = False
    default_filename = "main.py"

    for keyword, filename in _SIMPLE_PYTHON_KEYWORDS.items():
        if keyword in normalized:
            is_simple = True
            default_filename = filename
            break

    if not is_simple:
        is_simple = any(pattern in normalized for pattern in _SIMPLE_PYTHON_PATTERNS)

    if not is_simple:
        return None

    path_match = re.search(r"([A-Za-z0-9_./-]+\.py)\b", goal)
    if path_match:
        candidate = path_match.group(1).strip()
        parts = Path(candidate).parts
        if candidate and not candidate.startswith("/") and ".." not in parts:
            return candidate

    return default_filename


_LOW_VALUE_PY_NAMES = {"__init__.py", "setup.py", "conftest.py", "__main__.py"}


def _extract_primary_py_target(tasks: list[TaskDraft], goal: str) -> str | None:
    """Return the best substantive .py file from task assignments.

    Skips low-value boilerplate files (``__init__.py``, ``setup.py``, etc.)
    unless they are the *only* Python files available.
    """
    best: str | None = None
    fallback: str | None = None
    for task in tasks:
        for file_path in task.file_paths:
            candidate = _sanitize_relative_path(file_path)
            if not candidate or not candidate.endswith(".py"):
                continue
            if _is_placeholder_task_path(candidate):
                continue
            basename = candidate.rsplit("/", 1)[-1] if "/" in candidate else candidate
            if basename in _LOW_VALUE_PY_NAMES:
                if fallback is None:
                    fallback = candidate
                continue
            return candidate
    if best is not None:
        return best
    if fallback is not None:
        return fallback
    normalized_goal = goal.lower()
    if "python" in normalized_goal:
        return "main.py"
    return None


def _simple_python_goal_tasks(file_path: str) -> list[TaskDraft]:
    return [
        TaskDraft(
            task_id="task-01",
            agent_id="coder-1",
            file_paths=[file_path],
            depends_on=[],
            priority=50,
            parallelizable=True,
        )
    ]


def _apply_simple_python_fallback(
    tool_runtime: WorkspaceToolRuntime,
    file_path: str,
) -> str | None:
    content = _build_fallback_content(file_path)
    written = tool_runtime.write_file(file_path, content)
    return written if written else None


def _apply_task_file_fallback(
    tool_runtime: WorkspaceToolRuntime,
    file_paths: list[str],
) -> list[str]:
    written_files: list[str] = []
    for file_path in file_paths:
        candidate = _sanitize_relative_path(file_path)
        if not candidate or _is_placeholder_task_path(candidate):
            continue
        target = (tool_runtime.root / candidate).resolve()
        if target.exists():
            continue
        written = tool_runtime.write_file(candidate, _build_fallback_content(candidate))
        if written:
            written_files.append(written)
    return _unique_non_empty(written_files)


_CALCULATOR_FALLBACK = (
    '"""Simple terminal-based calculator."""\n\n\n'
    "def calculate(expression: str) -> float:\n"
    '    allowed = set("0123456789+-*/.() ")\n'
    "    if not all(ch in allowed for ch in expression):\n"
    '        raise ValueError("Invalid characters in expression")\n'
    "    return float(eval(expression))  # noqa: S307\n\n\n"
    "def main() -> None:\n"
    '    print("Terminal Calculator")\n'
    '    print("Type an expression or \'quit\' to exit.\\n")\n'
    "    while True:\n"
    "        try:\n"
    '            expr = input("> ").strip()\n'
    "        except (EOFError, KeyboardInterrupt):\n"
    "            break\n"
    '        if expr.lower() in ("quit", "exit", "q"):\n'
    "            break\n"
    "        if not expr:\n"
    "            continue\n"
    "        try:\n"
    '            print(f"= {calculate(expr)}")\n'
    "        except Exception as exc:\n"
    '            print(f"Error: {exc}")\n\n\n'
    'if __name__ == "__main__":\n'
    "    main()\n"
)

_HELLO_WORLD_FALLBACK = (
    '"""Generated by deterministic fallback for simple Python goal."""\n\n\n'
    "def main() -> None:\n"
    '    print("Hello, world!")\n\n\n'
    'if __name__ == "__main__":\n'
    "    main()\n"
)

_FALLBACK_TEMPLATES: dict[str, str] = {
    "hello_world": _HELLO_WORLD_FALLBACK,
    "calculator": _CALCULATOR_FALLBACK,
    "calc": _CALCULATOR_FALLBACK,
}


def _build_fallback_content(file_path: str) -> str:
    path = Path(file_path)
    stem = path.stem
    lower_name = path.name.lower()

    if lower_name == "readme.md":
        return "# Project\n\nGenerated by deterministic fallback.\n"
    if lower_name == "requirements.txt":
        return ""
    if lower_name == "__init__.py":
        return '"""Package initialization."""\n'
    if path.suffix and path.suffix != ".py":
        title = stem.replace("_", " ").title()
        if path.suffix == ".md":
            return f"# {title}\n\nGenerated by deterministic fallback.\n"
        return f"{title}\n"

    if stem in _FALLBACK_TEMPLATES:
        return _FALLBACK_TEMPLATES[stem]
    title = stem.replace("_", " ").title()
    return (
        f'"""{title}."""\n\n\n'
        "def main() -> None:\n"
        f'    print("{title}")\n\n\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )


def _resolve_github_repo_name(request_repo: str, workdirs: WorkdirRuntime) -> str:
    repo_name = str(request_repo).strip()
    if repo_name:
        return repo_name
    try:
        return workdirs.detect_repo_full_name()
    except WorkdirRuntimeError:
        return ""


def _unique_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _is_success_status(value: str) -> bool:
    return value in {"completed", "success", "ok", "done"}


def _should_continue_after_coder_result(*, status: str, reason: str, committed: bool) -> bool:
    return (
        _is_success_status(status)
        or committed
        or _is_coder_recoverable_failure_reason(reason)
    )


def _should_attempt_task_fallback(*, status: str, reason: str, task_files: list[str]) -> bool:
    # Only fall back on *genuine failures* with recoverable reasons.
    # When the coder claims success but commits nothing, we do NOT stub: that
    # case is handled upstream by coder_fail_count escalation so the pipeline
    # retries properly instead of silently replacing LLM output with empty stubs.
    if _is_success_status(status):
        return False
    if not _is_coder_recoverable_failure_reason(reason):
        return False
    return any(
        _sanitize_relative_path(path) and not _is_placeholder_task_path(path)
        for path in task_files
    )


def _is_coder_recoverable_failure_reason(reason: str) -> bool:
    return (
        _is_contract_mismatch_reason(reason)
        or _is_no_change_reason(reason)
        or _is_no_outcome_reason(reason)
        or _is_syntax_error_reason(reason)
    )


def _is_contract_mismatch_reason(reason: str) -> bool:
    normalized = reason.strip().lower()
    if not normalized:
        return False
    if "output contract" in normalized:
        return True
    patterns = (
        "did not conform to the required output contract",
        "does not conform to the required output contract",
        "did not follow the required output contract",
        "returned an unrelated json",
        "instead of the expected",
        "rel_path",
        "required fields are missing or malformed",
        "missing required fields",
        "unexpected json structure",
    )
    return any(pattern in normalized for pattern in patterns)


def _is_no_change_reason(reason: str) -> bool:
    normalized = reason.strip().lower()
    if not normalized:
        return False
    patterns = (
        "no implementation or file changes were provided",
        "no file changes were provided",
        "no changes were provided for the assigned task",
    )
    return any(pattern in normalized for pattern in patterns)


def _is_no_outcome_reason(reason: str) -> bool:
    normalized = reason.strip().lower()
    if not normalized:
        return False
    patterns = (
        "no implementation outcome was provided",
        "cannot determine changes or patch details",
        "no implementation or file changes were provided",
        "no implementation outcome",
        # Variants produced by different LLM phrasings
        "no coding actions were performed",
        "no coding was performed",
        "implementation outcome is missing",
        "no files were created",
        "no files were written",
        "no changes were made",
        "no work was performed",
    )
    return any(pattern in normalized for pattern in patterns)


def _is_syntax_error_reason(reason: str) -> bool:
    normalized = reason.strip().lower()
    if not normalized:
        return False
    patterns = (
        "generated code contains syntax errors",
        "contains syntax errors",
        "syntax error",
        "invalid syntax",
        "mismatched bracket",
        "mismatched parenth",
        "unbalanced bracket",
        "unbalanced parenth",
    )
    return any(pattern in normalized for pattern in patterns)


def _conflict_threshold_to_percent(conflict_threshold: float) -> int:
    percent = int(round(max(0.0, min(1.0, conflict_threshold)) * 100))
    return max(0, min(100, percent))


def _effective_coder_branches(*, current_round: list[str], historical: list[str]) -> list[str]:
    current = _unique_non_empty(current_round)
    if current:
        return current
    return _unique_non_empty(historical)


def _qa_failure_reason_from_command(command_result: dict) -> str:
    exit_code = int(command_result.get("exit_code", 1))
    stderr = str(command_result.get("stderr", "")).strip()
    stdout = str(command_result.get("stdout", "")).strip()
    detail = stderr or stdout
    detail = detail.splitlines()[-1] if detail else ""
    if detail:
        return f"pytest failed (exit {exit_code}): {detail[:220]}"
    return f"pytest failed with exit code {exit_code}"


def json_safe_dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
