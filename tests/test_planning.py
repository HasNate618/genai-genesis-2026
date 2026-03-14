"""
Tests for planning coordinator.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.planning import PlanningCoordinator


class TestPlanningCoordinator:
    """Test PlanningCoordinator."""
    
    @pytest.fixture
    def planning_coordinator(self, orchestration_engine, mock_store):
        """Create a PlanningCoordinator instance."""
        return PlanningCoordinator(
            orchestration_engine,
            mock_store,
            "http://localhost:8001",
            planning_timeout_seconds=5,
        )
    
    def test_trigger_planning(self, planning_coordinator, test_goal_id, mock_store):
        """Test triggering planning."""
        with patch.object(planning_coordinator, '_call_planning_agent', return_value="plan_123"):
            result = planning_coordinator.trigger_planning(test_goal_id)
        
        # Should still return False because we're not actually calling the agent
        # But the planning state should be set
        context = planning_coordinator.engine.get_context(test_goal_id)
        assert context.state.value == "planning"
    
    def test_get_plans(self, planning_coordinator, test_goal_id):
        """Test getting plans for a goal."""
        planning_coordinator.engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        planning_coordinator.engine.store_plan(test_goal_id, plan_data)
        
        plans = planning_coordinator.get_plans(test_goal_id)
        
        assert len(plans) == 1
    
    def test_has_plans(self, planning_coordinator, test_goal_id):
        """Test checking if plans exist."""
        planning_coordinator.engine.trigger_planning(test_goal_id)
        
        assert not planning_coordinator.has_plans(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        planning_coordinator.engine.store_plan(test_goal_id, plan_data)
        
        assert planning_coordinator.has_plans(test_goal_id)
    
    def test_transition_to_review(self, planning_coordinator, test_goal_id):
        """Test transitioning to review."""
        planning_coordinator.engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        planning_coordinator.engine.store_plan(test_goal_id, plan_data)
        
        result = planning_coordinator.transition_to_review(test_goal_id)
        
        assert result is True
