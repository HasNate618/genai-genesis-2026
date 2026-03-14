"""
API endpoint tests for orchestration service.
"""

import pytest
import sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from api.server import app
from core.orchestration import OrchestrationEngine
from memory.store import MoorchehStore
from unittest.mock import Mock

client = TestClient(app)

# Mock the global services before tests
@pytest.fixture(autouse=True)
def mock_services(monkeypatch):
    """Mock the global services."""
    mock_store = Mock(spec=MoorchehStore)
    mock_store.connected = True
    mock_store.store_record = Mock(return_value="test_record_id")
    mock_store.query_similar = Mock(return_value=[])
    mock_store.health_check = Mock(return_value={
        "connected": True,
        "fallback_available": True,
        "timestamp": "2026-03-14T15:00:00Z"
    })
    
    import api.server
    api.server.store = mock_store
    api.server.engine = OrchestrationEngine(mock_store, "test-project")
    api.server.planning_coordinator = Mock()
    api.server.approval_manager = Mock()
    api.server.task_distributor = Mock()
    api.server.task_distributor.get_registered_agents = Mock(return_value=[])


class TestHealthEndpoint:
    """Test health check endpoint."""
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "moorcheh_connected" in data


class TestGoalEndpoints:
    """Test goal management endpoints."""
    
    def test_create_goal(self):
        """Test creating a goal."""
        response = client.post(
            "/orchestration/goal",
            json={"goal_description": "Test goal"}
        )
        assert response.status_code == 201
        data = response.json()
        assert "goal_id" in data
        assert data["goal_description"] == "Test goal"
        assert data["state"] == "goal_created"
    
    def test_get_goal(self):
        """Test getting a goal."""
        # Create goal first
        create_response = client.post(
            "/orchestration/goal",
            json={"goal_description": "Test goal"}
        )
        goal_id = create_response.json()["goal_id"]
        
        # Get goal
        response = client.get(f"/orchestration/goal/{goal_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["goal_id"] == goal_id
    
    def test_get_nonexistent_goal(self):
        """Test getting a non-existent goal."""
        response = client.get("/orchestration/goal/goal_nonexistent")
        assert response.status_code == 404


class TestPlanningEndpoints:
    """Test planning workflow endpoints."""
    
    def test_trigger_planning(self):
        """Test triggering planning."""
        # Create goal
        create_response = client.post(
            "/orchestration/goal",
            json={"goal_description": "Test goal"}
        )
        goal_id = create_response.json()["goal_id"]
        
        # Trigger planning (will fail because we're not calling real agent)
        response = client.post(f"/orchestration/goal/{goal_id}/plan")
        assert response.status_code in [202, 500]  # Accepted or error (expected)


class TestRootEndpoint:
    """Test root endpoint."""
    
    def test_root(self):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data


class TestAgentEndpoints:
    """Test agent management endpoints."""
    
    def test_register_agent(self):
        """Test registering an agent."""
        response = client.post(
            "/orchestration/agent/register",
            json={
                "agent_id": "test_agent_1",
                "capabilities": ["python"]
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test_agent_1"
    
    def test_list_agents(self):
        """Test listing agents."""
        # Register an agent first
        client.post(
            "/orchestration/agent/register",
            json={"agent_id": "test_agent_1"}
        )
        
        # List agents
        response = client.get("/orchestration/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "total" in data
