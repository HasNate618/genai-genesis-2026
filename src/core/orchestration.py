"""
Orchestration state machine and coordinator.
Manages the lifecycle: GOAL_CREATED → PLANNING → PLAN_REVIEW → APPROVED → DISTRIBUTING_TASKS → TASKS_ASSIGNED
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Literal, Any
from datetime import datetime
from enum import Enum
import logging
import uuid

from memory.store import MoorchehStore
from memory.schemas import GoalRecord, PlanRecord, ApprovalRecord, TaskRecord

logger = logging.getLogger(__name__)


class OrchestrationState(str, Enum):
    """Valid states in the orchestration workflow."""
    GOAL_CREATED = "goal_created"
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    APPROVED = "approved"
    DISTRIBUTING_TASKS = "distributing_tasks"
    TASKS_ASSIGNED = "tasks_assigned"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OrchestrationContext:
    """Tracks the orchestration state and progress."""
    goal_id: str
    project_id: str
    state: OrchestrationState = OrchestrationState.GOAL_CREATED
    goal_description: str = ""
    goal_record_id: Optional[str] = None
    plans: Dict[str, Dict[str, Any]] = None  # plan_id -> plan_data
    approved_plan_id: Optional[str] = None
    tasks: Dict[str, Dict[str, Any]] = None  # task_id -> task_data
    created_at: str = ""
    updated_at: str = ""
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.plans is None:
            self.plans = {}
        if self.tasks is None:
            self.tasks = {}
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat() + "Z"
        if not self.updated_at:
            self.updated_at = self.created_at


class OrchestrationEngine:
    """Manages orchestration workflow state machine."""
    
    def __init__(self, store: MoorchehStore, project_id: str):
        """
        Initialize orchestration engine.
        
        Args:
            store: MoorchehStore instance
            project_id: Project identifier
        """
        self.store = store
        self.project_id = project_id
        self.contexts: Dict[str, OrchestrationContext] = {}
    
    def create_goal(self, goal_description: str) -> str:
        """
        Create a new goal for orchestration.
        
        Args:
            goal_description: Description of the goal
        
        Returns:
            Goal ID
        """
        goal_id = f"goal_{uuid.uuid4().hex[:8]}"
        context = OrchestrationContext(
            goal_id=goal_id,
            project_id=self.project_id,
            goal_description=goal_description,
        )
        self.contexts[goal_id] = context
        
        # Store goal record in memory
        goal_record = GoalRecord(
            project_id=self.project_id,
            agent_id="system",
            importance=5,
            payload={
                "goal_id": goal_id,
                "goal_description": goal_description,
            }
        )
        record_id = self.store.store_record(goal_record)
        context.goal_record_id = record_id
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        
        logger.info(f"Created goal {goal_id}: {goal_description}")
        return goal_id
    
    def get_context(self, goal_id: str) -> Optional[OrchestrationContext]:
        """Retrieve orchestration context for a goal."""
        return self.contexts.get(goal_id)
    
    def trigger_planning(self, goal_id: str) -> bool:
        """
        Transition to PLANNING state.
        
        Args:
            goal_id: Goal identifier
        
        Returns:
            True if transition was successful
        """
        context = self.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            return False
        
        if context.state != OrchestrationState.GOAL_CREATED:
            logger.error(f"Cannot trigger planning from state {context.state}")
            return False
        
        context.state = OrchestrationState.PLANNING
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        logger.info(f"Goal {goal_id} transitioned to PLANNING")
        return True
    
    def store_plan(self, goal_id: str, plan_data: Dict[str, Any]) -> str:
        """
        Store a generated plan for a goal.
        
        Args:
            goal_id: Goal identifier
            plan_data: Plan details (steps, effort, dependencies, etc.)
        
        Returns:
            Plan ID
        """
        context = self.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            raise ValueError(f"Goal {goal_id} not found")
        
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        context.plans[plan_id] = plan_data
        
        # Store plan record in memory
        plan_record = PlanRecord(
            project_id=self.project_id,
            agent_id=plan_data.get("planning_agent_id", "unknown"),
            importance=4,
            payload={
                "goal_id": goal_id,
                "plan_id": plan_id,
                "steps": plan_data.get("steps", []),
                "effort_estimate": plan_data.get("effort_estimate"),
                "dependencies": plan_data.get("dependencies", []),
                "risks": plan_data.get("risks", []),
            }
        )
        record_id = self.store.store_record(plan_record)
        context.plans[plan_id]["record_id"] = record_id
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        
        logger.info(f"Stored plan {plan_id} for goal {goal_id}")
        return plan_id
    
    def transition_to_review(self, goal_id: str) -> bool:
        """Transition to PLAN_REVIEW state."""
        context = self.get_context(goal_id)
        if not context or context.state != OrchestrationState.PLANNING:
            return False
        
        if not context.plans:
            logger.error(f"No plans available for goal {goal_id}")
            return False
        
        context.state = OrchestrationState.PLAN_REVIEW
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        logger.info(f"Goal {goal_id} transitioned to PLAN_REVIEW")
        return True
    
    def approve_plan(self, goal_id: str, plan_id: str, approval_notes: str = "") -> bool:
        """
        Approve a plan for a goal.
        
        Args:
            goal_id: Goal identifier
            plan_id: Plan identifier to approve
            approval_notes: Optional notes from approver
        
        Returns:
            True if approval was successful
        """
        context = self.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            return False
        
        if plan_id not in context.plans:
            logger.error(f"Plan {plan_id} not found for goal {goal_id}")
            return False
        
        if context.state != OrchestrationState.PLAN_REVIEW:
            logger.error(f"Cannot approve plan from state {context.state}")
            return False
        
        # Store approval record
        approval_record = ApprovalRecord(
            project_id=self.project_id,
            agent_id="system",
            importance=5,
            payload={
                "goal_id": goal_id,
                "plan_id": plan_id,
                "decision": "approved",
                "approval_notes": approval_notes,
            }
        )
        record_id = self.store.store_record(approval_record)
        
        context.approved_plan_id = plan_id
        context.state = OrchestrationState.APPROVED
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        
        logger.info(f"Plan {plan_id} approved for goal {goal_id}")
        return True
    
    def reject_plan(self, goal_id: str, plan_id: str, rejection_reason: str) -> bool:
        """
        Reject a plan and return to planning.
        
        Args:
            goal_id: Goal identifier
            plan_id: Plan identifier to reject
            rejection_reason: Reason for rejection
        
        Returns:
            True if rejection was successful
        """
        context = self.get_context(goal_id)
        if not context or context.state != OrchestrationState.PLAN_REVIEW:
            return False
        
        # Store rejection record
        from memory.schemas import PlanRejectionRecord
        rejection_record = PlanRejectionRecord(
            project_id=self.project_id,
            agent_id="system",
            importance=4,
            payload={
                "goal_id": goal_id,
                "plan_id": plan_id,
                "rejection_reason": rejection_reason,
            }
        )
        self.store.store_record(rejection_record)
        
        # Return to planning
        context.state = OrchestrationState.PLANNING
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        
        logger.info(f"Plan {plan_id} rejected for goal {goal_id}. Returning to planning.")
        return True
    
    def create_task(self, goal_id: str, task_data: Dict[str, Any]) -> str:
        """
        Create a task from approved plan.
        
        Args:
            goal_id: Goal identifier
            task_data: Task details (name, description, dependencies, etc.)
        
        Returns:
            Task ID
        """
        context = self.get_context(goal_id)
        if not context:
            raise ValueError(f"Goal {goal_id} not found")
        
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        context.tasks[task_id] = task_data
        
        # Store task record
        task_record = TaskRecord(
            project_id=self.project_id,
            agent_id=task_data.get("assigned_agent_id"),
            importance=4,
            payload={
                "goal_id": goal_id,
                "task_id": task_id,
                "task_name": task_data.get("task_name"),
                "description": task_data.get("description"),
                "acceptance_criteria": task_data.get("acceptance_criteria", []),
                "dependencies": task_data.get("dependencies", []),
                "files_involved": task_data.get("files_involved", []),
            }
        )
        record_id = self.store.store_record(task_record)
        context.tasks[task_id]["record_id"] = record_id
        
        logger.info(f"Created task {task_id} from plan for goal {goal_id}")
        return task_id
    
    def transition_to_tasks_assigned(self, goal_id: str) -> bool:
        """Transition to TASKS_ASSIGNED state."""
        context = self.get_context(goal_id)
        if not context or context.state != OrchestrationState.DISTRIBUTING_TASKS:
            return False
        
        context.state = OrchestrationState.TASKS_ASSIGNED
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        logger.info(f"Goal {goal_id} transitioned to TASKS_ASSIGNED")
        return True
    
    def set_failed(self, goal_id: str, error_message: str) -> bool:
        """Mark orchestration as failed."""
        context = self.get_context(goal_id)
        if not context:
            return False
        
        context.state = OrchestrationState.FAILED
        context.error_message = error_message
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        logger.error(f"Goal {goal_id} marked as FAILED: {error_message}")
        return True
    
    def cancel(self, goal_id: str) -> bool:
        """Cancel orchestration for a goal."""
        context = self.get_context(goal_id)
        if not context:
            return False
        
        context.state = OrchestrationState.CANCELLED
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        logger.info(f"Goal {goal_id} orchestration cancelled")
        return True
