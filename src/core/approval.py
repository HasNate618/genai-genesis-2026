"""
Approval manager: handles approval workflow for plans.
"""

import logging
from typing import List, Optional, Any

from memory.store import MoorchehStore
from core.orchestration import OrchestrationEngine

logger = logging.getLogger(__name__)


class ApprovalManager:
    """Manages approval workflow."""
    
    def __init__(self, engine: OrchestrationEngine, store: MoorchehStore):
        """
        Initialize approval manager.
        
        Args:
            engine: OrchestrationEngine instance
            store: MoorchehStore instance
        """
        self.engine = engine
        self.store = store
    
    def get_plans_for_approval(self, goal_id: str) -> List[tuple]:
        """
        Get plans ready for approval.
        
        Args:
            goal_id: Goal identifier
        
        Returns:
            List of (plan_id, plan_data) tuples
        """
        context = self.engine.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            return []
        
        # Transition to review state if not already
        if context.state.value == "planning":
            self.engine.transition_to_review(goal_id)
        
        return list(context.plans.items())
    
    def approve_plan(self, goal_id: str, plan_id: str, approval_notes: str = "") -> bool:
        """
        Approve a plan.
        
        Args:
            goal_id: Goal identifier
            plan_id: Plan identifier to approve
            approval_notes: Optional notes from approver
        
        Returns:
            True if approval succeeded
        """
        context = self.engine.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            return False
        
        if plan_id not in context.plans:
            logger.error(f"Plan {plan_id} not found")
            return False
        
        success = self.engine.approve_plan(goal_id, plan_id, approval_notes)
        
        if success:
            logger.info(f"Plan {plan_id} approved for goal {goal_id}")
        else:
            logger.error(f"Failed to approve plan {plan_id} for goal {goal_id}")
        
        return success
    
    def reject_plan(self, goal_id: str, plan_id: str, rejection_reason: str) -> bool:
        """
        Reject a plan and return to planning.
        
        Args:
            goal_id: Goal identifier
            plan_id: Plan identifier to reject
            rejection_reason: Reason for rejection
        
        Returns:
            True if rejection succeeded
        """
        context = self.engine.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            return False
        
        if plan_id not in context.plans:
            logger.error(f"Plan {plan_id} not found")
            return False
        
        success = self.engine.reject_plan(goal_id, plan_id, rejection_reason)
        
        if success:
            logger.info(f"Plan {plan_id} rejected for goal {goal_id}. Returning to planning.")
        else:
            logger.error(f"Failed to reject plan {plan_id} for goal {goal_id}")
        
        return success
    
    def get_approval_status(self, goal_id: str) -> Optional[dict]:
        """
        Get approval status for a goal.
        
        Args:
            goal_id: Goal identifier
        
        Returns:
            Status dictionary or None
        """
        context = self.engine.get_context(goal_id)
        if not context:
            return None
        
        return {
            "goal_id": goal_id,
            "state": context.state.value,
            "total_plans": len(context.plans),
            "approved_plan_id": context.approved_plan_id,
            "plans_ready_for_approval": len(context.plans) > 0 and context.state.value == "plan_review",
        }
