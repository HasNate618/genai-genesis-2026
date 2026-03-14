"""
Tests for orchestration state machine.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.orchestration import OrchestrationEngine, OrchestrationState


class TestOrchestrationEngine:
    """Test OrchestrationEngine state machine."""
    
    def test_create_goal(self, orchestration_engine, mock_store):
        """Test creating a goal."""
        goal_id = orchestration_engine.create_goal("Test goal")
        
        assert goal_id.startswith("goal_")
        context = orchestration_engine.get_context(goal_id)
        assert context is not None
        assert context.goal_description == "Test goal"
        assert context.state == OrchestrationState.GOAL_CREATED
    
    def test_trigger_planning(self, orchestration_engine, test_goal_id):
        """Test triggering planning."""
        result = orchestration_engine.trigger_planning(test_goal_id)
        
        assert result is True
        context = orchestration_engine.get_context(test_goal_id)
        assert context.state == OrchestrationState.PLANNING
    
    def test_trigger_planning_invalid_state(self, orchestration_engine, test_goal_id):
        """Test triggering planning from invalid state."""
        orchestration_engine.trigger_planning(test_goal_id)
        result = orchestration_engine.trigger_planning(test_goal_id)
        
        assert result is False
    
    def test_store_plan(self, orchestration_engine, test_goal_id, mock_store):
        """Test storing a plan."""
        orchestration_engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1", "description": "Do something"}],
            "effort_estimate": "4 hours",
        }
        
        plan_id = orchestration_engine.store_plan(test_goal_id, plan_data)
        
        assert plan_id.startswith("plan_")
        context = orchestration_engine.get_context(test_goal_id)
        assert plan_id in context.plans
        # Should be called at least once (store_record is also called during goal creation)
        assert mock_store.store_record.call_count >= 1
    
    def test_transition_to_review(self, orchestration_engine, test_goal_id):
        """Test transitioning to plan review."""
        orchestration_engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        orchestration_engine.store_plan(test_goal_id, plan_data)
        
        result = orchestration_engine.transition_to_review(test_goal_id)
        
        assert result is True
        context = orchestration_engine.get_context(test_goal_id)
        assert context.state == OrchestrationState.PLAN_REVIEW
    
    def test_approve_plan(self, orchestration_engine, test_goal_id, mock_store):
        """Test approving a plan."""
        orchestration_engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        plan_id = orchestration_engine.store_plan(test_goal_id, plan_data)
        orchestration_engine.transition_to_review(test_goal_id)
        
        result = orchestration_engine.approve_plan(test_goal_id, plan_id, "Looks good")
        
        assert result is True
        context = orchestration_engine.get_context(test_goal_id)
        assert context.approved_plan_id == plan_id
        assert context.state == OrchestrationState.APPROVED
    
    def test_reject_plan(self, orchestration_engine, test_goal_id, mock_store):
        """Test rejecting a plan."""
        orchestration_engine.trigger_planning(test_goal_id)
        
        plan_data = {
            "planning_agent_id": "agent_1",
            "steps": [{"name": "Step 1"}],
        }
        plan_id = orchestration_engine.store_plan(test_goal_id, plan_data)
        orchestration_engine.transition_to_review(test_goal_id)
        
        result = orchestration_engine.reject_plan(test_goal_id, plan_id, "Not detailed enough")
        
        assert result is True
        context = orchestration_engine.get_context(test_goal_id)
        assert context.state == OrchestrationState.PLANNING
    
    def test_create_task(self, orchestration_engine, test_goal_id):
        """Test creating a task."""
        task_data = {
            "task_name": "Implement feature",
            "description": "Implement the feature",
            "acceptance_criteria": ["Requirement 1"],
            "dependencies": [],
            "files_involved": ["src/feature.py"],
        }
        
        task_id = orchestration_engine.create_task(test_goal_id, task_data)
        
        assert task_id.startswith("task_")
        context = orchestration_engine.get_context(test_goal_id)
        assert task_id in context.tasks
    
    def test_cancel_goal(self, orchestration_engine, test_goal_id):
        """Test cancelling a goal."""
        result = orchestration_engine.cancel(test_goal_id)
        
        assert result is True
        context = orchestration_engine.get_context(test_goal_id)
        assert context.state == OrchestrationState.CANCELLED
    
    def test_set_failed(self, orchestration_engine, test_goal_id):
        """Test marking goal as failed."""
        result = orchestration_engine.set_failed(test_goal_id, "Test error")
        
        assert result is True
        context = orchestration_engine.get_context(test_goal_id)
        assert context.state == OrchestrationState.FAILED
        assert context.error_message == "Test error"
