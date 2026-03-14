"""
Tests for task distributor.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.task_distributor import TaskDistributor


class TestTaskDistributor:
    """Test TaskDistributor."""
    
    @pytest.fixture
    def task_distributor(self, orchestration_engine, mock_store):
        """Create a TaskDistributor instance."""
        return TaskDistributor(
            orchestration_engine,
            mock_store,
            "http://localhost:8001",
            assignment_strategy="round_robin",
        )
    
    def test_register_agent(self, task_distributor):
        """Test registering an agent."""
        result = task_distributor.register_agent("agent_1")
        
        assert result is True
        assert "agent_1" in task_distributor.get_registered_agents()
    
    def test_get_registered_agents(self, task_distributor):
        """Test getting registered agents."""
        task_distributor.register_agent("agent_1")
        task_distributor.register_agent("agent_2")
        
        agents = task_distributor.get_registered_agents()
        
        assert len(agents) >= 2
        assert "agent_1" in agents
        assert "agent_2" in agents
    
    def test_parse_plan_into_tasks(self, task_distributor, test_goal_id):
        """Test parsing plan into tasks."""
        plan = {
            "steps": [
                {
                    "name": "Task 1",
                    "description": "First task",
                    "acceptance_criteria": ["Criterion 1"],
                },
                {
                    "name": "Task 2",
                    "description": "Second task",
                    "files": ["src/file.py"],
                }
            ]
        }
        
        tasks = task_distributor._parse_plan_into_tasks(test_goal_id, plan)
        
        assert len(tasks) == 2
        assert tasks[0]["task_name"] == "Task 1"
        assert tasks[1]["task_name"] == "Task 2"
    
    def test_assign_tasks_round_robin(self, task_distributor):
        """Test round-robin task assignment."""
        task_distributor.register_agent("agent_1")
        task_distributor.register_agent("agent_2")
        
        tasks = [
            {"task_name": f"Task {i}"} for i in range(4)
        ]
        
        assignments = task_distributor._assign_tasks_to_agents(tasks)
        
        assert len(assignments) == 4
        # Round-robin should alternate agents
        assert assignments[0][1] == "agent_1"
        assert assignments[1][1] == "agent_2"
        assert assignments[2][1] == "agent_1"
        assert assignments[3][1] == "agent_2"
    
    def test_update_agent_state(self, task_distributor, mock_store):
        """Test updating agent state."""
        result = task_distributor.update_agent_state(
            "agent_1",
            "test-project",
            ["task_1", "task_2"]
        )
        
        assert result is True
        mock_store.store_record.assert_called_once()
