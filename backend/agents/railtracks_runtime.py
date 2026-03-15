"""Railtracks-backed multi-agent runtime for planning/coding/merge/qa phases."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.config import Settings
from backend.core.tool_runtime import WorkspaceToolRuntime


class RailtracksRuntimeError(RuntimeError):
    """Raised when Railtracks execution or contract parsing fails."""


class PlanSummary(BaseModel):
    primary_strategy: str = ""
    estimated_task_count: int = 0


class PlannerOutput(BaseModel):
    status: str = "ok"
    plan_round: int = 1
    plan: str
    summary: PlanSummary = Field(default_factory=PlanSummary)
    next_action: str = "await_plan_user_approval"
    next_action_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class CoordinatorSummary(BaseModel):
    total_tasks: int = 0
    agents_used: int = 0
    unassigned_tasks: int = 0


class CoordinatorAssignment(BaseModel):
    task_id: str
    task_summary: str
    assigned_agent_id: str
    assigned_agent_role: str = "coder"
    phase: str = "execution"
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = ""
    predicted_files: list[str] = Field(default_factory=list)
    predicted_components: list[str] = Field(default_factory=list)


class CoordinatorOutput(BaseModel):
    status: str = "ok"
    summary: CoordinatorSummary = Field(default_factory=CoordinatorSummary)
    assignments: list[CoordinatorAssignment] = Field(default_factory=list)
    loop_context_applied: bool = False
    next_action: str = "send_to_conflict_analysis"
    next_action_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class ConflictPairScore(BaseModel):
    agent_a_id: str = ""
    agent_b_id: str = ""
    conflict_score: float = 0.0
    drivers: list[str] = Field(default_factory=list)


class ConflictHotspot(BaseModel):
    task_a_id: str = ""
    task_b_id: str = ""
    score: float = 0.0
    reason: str = ""


class ConflictOutput(BaseModel):
    status: str = "ok"
    overall_conflict_score: float = 0.0
    threshold_percent: int = 20
    threshold_breached: bool = False
    is_acceptable: bool = True
    agent_pair_scores: list[ConflictPairScore] = Field(default_factory=list)
    task_hotspots: list[ConflictHotspot] = Field(default_factory=list)
    next_action: str = "proceed_to_user_agents"
    next_action_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class CodingOutput(BaseModel):
    status: str = "completed"
    changed_files: list[str] = Field(default_factory=list)
    patch_summary: str = ""
    next_action: str = "send_to_merge"
    next_action_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class MergeSummary(BaseModel):
    total_outputs: int = 0
    files_touched: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0


class MergeConflict(BaseModel):
    file: str = ""
    agents_involved: list[str] = Field(default_factory=list)
    reason: str = ""
    resolution: str = ""


class MergeOutput(BaseModel):
    status: str = "success"
    mergeable: bool = True
    summary: MergeSummary = Field(default_factory=MergeSummary)
    resolved_conflicts: list[MergeConflict] = Field(default_factory=list)
    unresolved_conflicts: list[MergeConflict] = Field(default_factory=list)
    next_action: str = "proceed_to_qa"
    next_action_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class QAExecutionResult(BaseModel):
    command: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""


class QAReportSummary(BaseModel):
    commands_run: int = 0
    commands_passed: int = 0
    commands_failed: int = 0


class QAFailureReport(BaseModel):
    root_causes: list[str] = Field(default_factory=list)
    failed_commands: list[str] = Field(default_factory=list)


class QAOutput(BaseModel):
    status: str = "success"
    qa_passed: bool = True
    summary: QAReportSummary = Field(default_factory=QAReportSummary)
    execution_results: list[QAExecutionResult] = Field(default_factory=list)
    failure_report: QAFailureReport = Field(default_factory=QAFailureReport)
    next_action: str = "await_user_acceptance"
    next_action_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class RailtracksWorkflowRuntime:
    """Runs contract-constrained agents using Railtracks."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            import railtracks as rt  # type: ignore
        except ImportError as exc:
            raise RailtracksRuntimeError(
                "railtracks is required for runtime execution. Install with `pip install railtracks`."
            ) from exc
        self.rt = rt
        self.llm = self._build_llm()
        self.contracts_dir = Path(__file__).resolve().parent

    async def run_planner(
        self, *, goal: str, plan_round: int, revision_feedback: str, max_coder_agents: int
    ) -> PlannerOutput:
        payload = {
            "goal": goal,
            "plan_round": plan_round,
            "revision_context": {
                "source": "plan_rejection" if revision_feedback else "none",
                "feedback": revision_feedback,
            },
            "constraints": {"max_coder_agents": max_coder_agents},
        }
        return await self._call_contract(
            contract_filename="planning_agent.md",
            payload=payload,
            output_schema=PlannerOutput,
            agent_name="planner-agent",
        )

    async def run_task_coordinator(
        self,
        *,
        goal: str,
        plan: str,
        coder_count: int,
        loop_source: str,
        loop_reason: str,
    ) -> CoordinatorOutput:
        agents = [
            {
                "id": f"coder-{index + 1}",
                "role": "coder",
                "capabilities": ["read", "write", "edit", "bash", "git", "github", "glob", "search"],
                "constraints": [],
                "current_load": 0,
            }
            for index in range(max(1, coder_count))
        ]
        payload = {
            "goal": goal,
            "plan": plan,
            "plan_approval": {"approved": True},
            "agents": agents,
            "loop_context": {"source": loop_source or "none", "reason": loop_reason},
            "constraints": {"max_parallel_agents": coder_count, "must_review_dependencies": True},
        }
        return await self._call_contract(
            contract_filename="task_coordinator_agent.md",
            payload=payload,
            output_schema=CoordinatorOutput,
            agent_name="task-coordinator-agent",
        )

    async def run_conflict_analysis(
        self,
        *,
        goal: str,
        plan: str,
        assignments: list[dict[str, Any]],
        threshold_percent: int,
    ) -> ConflictOutput:
        payload = {
            "goal": goal,
            "plan": plan,
            "task_distribution": {"assignments": assignments},
            "agents": [
                {
                    "id": assignment.get("assigned_agent_id", ""),
                    "role": assignment.get("assigned_agent_role", "coder"),
                    "capabilities": ["read", "write", "bash", "git"],
                }
                for assignment in assignments
            ],
            "constraints": {"conflict_threshold_percent": threshold_percent},
        }
        return await self._call_contract(
            contract_filename="conflict_analysis_agent.md",
            payload=payload,
            output_schema=ConflictOutput,
            agent_name="conflict-analysis-agent",
        )

    async def run_coder(
        self,
        *,
        goal: str,
        plan: str,
        assigned_agent_id: str,
        task_list: list[dict[str, Any]],
        retry_context: dict[str, Any],
        tool_runtime: WorkspaceToolRuntime,
    ) -> CodingOutput:
        payload = {
            "goal": goal,
            "plan": plan,
            "assigned_agent_id": assigned_agent_id,
            "task_list": task_list,
            "retry_context": retry_context,
        }
        tool_nodes = tool_runtime.build_railtracks_tool_nodes(self.rt)
        return await self._call_contract(
            contract_filename="coding_agent.md",
            payload=payload,
            output_schema=CodingOutput,
            agent_name=f"coding-agent-{assigned_agent_id}",
            tool_nodes=tool_nodes,
        )

    async def run_merge(
        self,
        *,
        goal: str,
        plan: str,
        assignments: list[dict[str, Any]],
        agent_outputs: list[dict[str, Any]],
    ) -> MergeOutput:
        payload = {
            "goal": goal,
            "plan": plan,
            "task_distribution": {"assignments": assignments},
            "agent_outputs": agent_outputs,
            "constraints": {"allow_auto_resolution": True},
        }
        return await self._call_contract(
            contract_filename="merge_agent.md",
            payload=payload,
            output_schema=MergeOutput,
            agent_name="merge-agent",
        )

    async def run_qa(
        self,
        *,
        goal: str,
        plan: str,
        merged_output: dict[str, Any],
        workspace_path: str,
        run_command: str,
        test_commands: list[str],
        tool_runtime: WorkspaceToolRuntime | None = None,
    ) -> QAOutput:
        payload = {
            "goal": goal,
            "plan": plan,
            "merged_output": merged_output,
            "workspace_path": workspace_path,
            "run_command": run_command,
            "test_commands": test_commands,
            "constraints": {"stop_on_first_failure": False, "max_log_bytes_per_command": 2_000_000},
            "copilot_code_review": {"enabled": False, "scope": "changed_files"},
        }
        tool_nodes = tool_runtime.build_railtracks_tool_nodes(self.rt) if tool_runtime else None
        return await self._call_contract(
            contract_filename="qa_agent.md",
            payload=payload,
            output_schema=QAOutput,
            agent_name="qa-agent",
            tool_nodes=tool_nodes,
        )

    def _build_llm(self) -> Any:
        llm_module = self.rt.llm
        if hasattr(llm_module, "OpenAICompatibleProvider"):
            return llm_module.OpenAICompatibleProvider(
                self.settings.llm_model,
                api_base=self.settings.llm_base_url,
                api_key=self.settings.llm_api_key,
            )

        if hasattr(llm_module, "OpenAILLM"):
            try:
                return llm_module.OpenAILLM(
                    self.settings.llm_model,
                    api_base=self.settings.llm_base_url,
                    api_key=self.settings.llm_api_key,
                )
            except TypeError:
                return llm_module.OpenAILLM(self.settings.llm_model)

        raise RailtracksRuntimeError("Unsupported Railtracks LLM module; missing compatible provider.")

    async def _call_contract(
        self,
        *,
        contract_filename: str,
        payload: dict[str, Any],
        output_schema: type[BaseModel],
        agent_name: str,
        tool_nodes: list[Any] | None = None,
    ) -> Any:
        contract_text = self._load_contract(contract_filename)
        system_message = (
            f"{contract_text}\n\n"
            "Follow the contract exactly. Return only valid JSON with no markdown fencing."
        )

        kwargs: dict[str, Any] = {
            "name": agent_name,
            "llm": self.llm,
            "system_message": system_message,
            "output_schema": output_schema,
        }
        if tool_nodes:
            kwargs["tool_nodes"] = tool_nodes

        agent = self.rt.agent_node(**kwargs)
        prompt = json.dumps(payload, ensure_ascii=False)
        try:
            result = await asyncio.wait_for(
                self.rt.call(agent, prompt),
                timeout=self.settings.llm_call_timeout_seconds,
            )
        except TimeoutError as exc:
            raise RailtracksRuntimeError(
                f"Agent '{agent_name}' timed out after {self.settings.llm_call_timeout_seconds}s."
            ) from exc

        structured = getattr(result, "structured", None)
        if isinstance(structured, output_schema):
            return structured
        if isinstance(structured, dict):
            return output_schema.model_validate(structured)

        text = str(getattr(result, "text", "")).strip()
        if not text:
            raise RailtracksRuntimeError(
                f"Agent '{agent_name}' returned no structured result and empty text."
            )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RailtracksRuntimeError(
                f"Agent '{agent_name}' returned non-JSON output: {text[:500]}"
            ) from exc
        return output_schema.model_validate(parsed)

    def _load_contract(self, contract_filename: str) -> str:
        path = self.contracts_dir / contract_filename
        if not path.is_file():
            raise RailtracksRuntimeError(f"Missing contract file: {path}")
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise RailtracksRuntimeError(f"Contract file is empty: {path}")
        return text
