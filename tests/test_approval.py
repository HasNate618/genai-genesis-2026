"""
Tests for approval manager.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.approval import ApprovalManager


class TestApprovalManager:
    """Test ApprovalManager."""
    
    @pytest.fixture
    def approval_manager(self, orchestration_engine, mock_store):
        """Create an ApprovalManager instance."""
        return ApprovalManager(orchestration_engine, mock_store)
    
    def test_get_plans_for_approval(self, approval_manager, test_goal_id):
        """Test getting plans for approval."""
        approval_manager.engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        plan_id = approval_manager.engine.store_plan(test_goal_id, plan_data)
        
        plans = approval_manager.get_plans_for_approval(test_goal_id)
        
        assert len(plans) == 1
        assert plans[0][0] == plan_id
    
    def test_approve_plan(self, approval_manager, test_goal_id, mock_store):
        """Test approving a plan."""
        approval_manager.engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        plan_id = approval_manager.engine.store_plan(test_goal_id, plan_data)
        approval_manager.engine.transition_to_review(test_goal_id)
        
        result = approval_manager.approve_plan(test_goal_id, plan_id, "Good plan")
        
        assert result is True
        context = approval_manager.engine.get_context(test_goal_id)
        assert context.approved_plan_id == plan_id
    
    def test_reject_plan(self, approval_manager, test_goal_id, mock_store):
        """Test rejecting a plan."""
        approval_manager.engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        plan_id = approval_manager.engine.store_plan(test_goal_id, plan_data)
        approval_manager.engine.transition_to_review(test_goal_id)
        
        result = approval_manager.reject_plan(test_goal_id, plan_id, "Need more details")
        
        assert result is True
        context = approval_manager.engine.get_context(test_goal_id)
        assert context.state.value == "planning"
    
    def test_get_approval_status(self, approval_manager, test_goal_id):
        """Test getting approval status."""
        status = approval_manager.get_approval_status(test_goal_id)
        
        assert status is not None
        assert status["goal_id"] == test_goal_id
        assert status["total_plans"] == 0
