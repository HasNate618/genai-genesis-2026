"""
Pydantic models for orchestration API requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


class GoalRequest(BaseModel):
    """Request to create a goal."""
    goal_description: str = Field(..., description="Description of the goal")


class GoalResponse(BaseModel):
    """Response with goal details."""
    goal_id: str
    goal_description: str
    state: str
    created_at: str
    updated_at: str


class PlanStep(BaseModel):
    """A single step in a plan."""
    name: str
    description: str
    files: Optional[List[str]] = []
    dependencies: Optional[List[str]] = []
    acceptance_criteria: Optional[List[str]] = []
    effort_estimate: Optional[str] = "unknown"


class GeneratePlanRequest(BaseModel):
    """Request to generate a plan for a goal."""
    goal_id: str
    planning_agent_id: Optional[str] = "planning_agent"


class PlanSubmissionRequest(BaseModel):
    """Submission of a generated plan from planning agent."""
    goal_id: str
    planning_agent_id: str
    steps: List[PlanStep]
    effort_estimate: Optional[str] = None
    dependencies: Optional[List[str]] = []
    risks: Optional[List[str]] = []
    rationale: Optional[str] = ""


class PlanResponse(BaseModel):
    """Response with plan details."""
    plan_id: str
    goal_id: str
    planning_agent_id: str
    steps: List[PlanStep]
    effort_estimate: Optional[str]
    dependencies: List[str]
    risks: List[str]
    rationale: str
    created_at: str


class ApprovalDecisionRequest(BaseModel):
    """Request to approve or reject a plan."""
    goal_id: str
    plan_id: str
    decision: Literal["approve", "reject"]
    notes: Optional[str] = ""


class ApprovalStatusResponse(BaseModel):
    """Response with approval status."""
    goal_id: str
    state: str
    total_plans: int
    approved_plan_id: Optional[str]
    plans_ready_for_approval: bool


class TaskRequest(BaseModel):
    """Request to trigger task distribution."""
    goal_id: str


class TaskResponse(BaseModel):
    """Response with task details."""
    task_id: str
    goal_id: str
    assigned_agent_id: str
    task_name: str
    description: str
    acceptance_criteria: List[str]
    dependencies: List[str]
    files_involved: List[str]
    effort_estimate: str


class TasksListResponse(BaseModel):
    """Response with list of tasks."""
    goal_id: str
    tasks: List[TaskResponse]
    total_tasks: int


class OrchestrationStatusResponse(BaseModel):
    """Full orchestration status for a goal."""
    goal_id: str
    goal_description: str
    state: str
    created_at: str
    updated_at: str
    total_plans: int
    approved_plan_id: Optional[str]
    total_tasks: int
    error_message: Optional[str]


class AgentRegistrationRequest(BaseModel):
    """Request to register an agent."""
    agent_id: str
    capabilities: Optional[List[str]] = []


class HealthCheckResponse(BaseModel):
    """Health check response."""
    status: str
    moorcheh_connected: bool
    fallback_available: bool
    timestamp: str


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None
    timestamp: str
