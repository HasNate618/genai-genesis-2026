"""In-memory job runtime and pipeline state machine for `/api/v1` endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

from backend.config import Settings
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
    gemini_key: str
    moorcheh_key: str


@dataclass(frozen=True)
class JobReview:
    """Human review payload for plan/result gates."""

    approved: bool
    feedback: str


@dataclass(frozen=True)
class JobMemoryHooks:
    """Moorcheh-backed helpers consumed inside phase transitions."""

    writer: WorkflowContextWriter
    reader: WorkflowContextReader
    compensator: ConflictCompensator


class JobRuntime:
    """Runs the architecture-defined 3-phase job flow with HITL gates."""

    def __init__(
        self,
        *,
        tick_seconds: float = 0.05,
        memory_factory: Callable[[JobLaunchRequest], JobMemoryHooks | None] | None = None,
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
        hooks: JobMemoryHooks | None = None
        try:
            await self._set_status(job_id, STATUS_PLANNING)
            await self._set_agent_states(job_id, planner="running")
            await self._append_log(job_id, "Planning phase started.")

            hooks = await asyncio.to_thread(self._memory_factory, request)
            if hooks is not None:
                await asyncio.to_thread(
                    hooks.writer.write_goal,
                    workflow_id=job_id,
                    run_id=run_id,
                    goal_text=request.goal,
                )

            feedback_hint = ""
            planning_iteration = 1
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

                plan_text = _build_plan_markdown(
                    goal=request.goal,
                    context_summary=context_summary,
                    feedback_hint=feedback_hint,
                    iteration=planning_iteration,
                )
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

                feedback_hint = plan_review.feedback
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

            await self._set_status(job_id, STATUS_COORDINATING)
            await self._set_agent_states(job_id, planner="done", conflict_manager="running")
            await self._append_log(job_id, "Coordination phase started.")
            draft_tasks = _draft_tasks(request.coder_count)
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
            await self._sleep_tick()

            while True:
                await self._set_status(job_id, STATUS_CODING)
                await self._set_agent_states(job_id, conflict_manager="done", coder="running")
                await self._append_log(job_id, "Coding phase started.")

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
                    await self._sleep_tick()
                    if hooks is not None:
                        await asyncio.to_thread(
                            hooks.writer.write_task_update,
                            workflow_id=job_id,
                            run_id=run_id,
                            task_id=task.task_id,
                            summary=f"{task.agent_id} completed work",
                            status="done",
                            agent_id=task.agent_id,
                            file_paths=task.file_paths,
                            depends_on=task.depends_on,
                        )

                await self._set_status(job_id, STATUS_VERIFYING)
                await self._set_agent_states(job_id, coder="done", verification="running")
                await self._append_log(job_id, "Verification phase started.")
                await self._sleep_tick()
                verification_summary = f"Verification completed for {len(adjusted_tasks)} task(s)."
                if hooks is not None:
                    await asyncio.to_thread(
                        hooks.writer.write_event,
                        workflow_id=job_id,
                        run_id=run_id,
                        record_type=RecordType.QA,
                        stage=WorkflowStage.QA,
                        status="done",
                        raw_text=verification_summary,
                        agent_id="verification",
                    )

                await self._set_status(job_id, STATUS_REVIEW_READY)
                await self._set_agent_states(job_id, verification="waiting_review")
                await self._append_log(job_id, "Waiting for final result review.")
                await self._result_events[job_id].wait()
                self._result_events[job_id].clear()

                result_review = await self._read_review(job_id, key="result_feedback")
                if result_review.approved:
                    await self._append_log(job_id, "Result approved. Finalizing job.")
                    if hooks is not None:
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
                        conflict_manager="done",
                        coder="done",
                        verification="done",
                    )
                    break

                await self._append_log(job_id, "Result rejected. Looping back to coding.")
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
                conflict_manager="failed",
                coder="failed",
                verification="failed",
            )
            await self._append_log(job_id, f"Pipeline failed: {exc}")

    def _build_memory_hooks(self, request: JobLaunchRequest) -> JobMemoryHooks:
        settings = Settings.from_env(moorcheh_api_key=request.moorcheh_key)
        store = MoorchehVectorStore(settings=settings)
        store.provision_namespace()
        writer = WorkflowContextWriter(store)
        reader = WorkflowContextReader(store)
        compensator = ConflictCompensator(settings=settings)
        return JobMemoryHooks(writer=writer, reader=reader, compensator=compensator)

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
        "conflict_manager": "idle",
        "coder": "idle",
        "verification": "idle",
    }


def _build_plan_markdown(
    *, goal: str, context_summary: str, feedback_hint: str, iteration: int
) -> str:
    lines = [
        f"# Plan Iteration {iteration}",
        "",
        f"## Goal",
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
