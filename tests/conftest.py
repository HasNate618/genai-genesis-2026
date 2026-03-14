"""
Test configuration and fixtures.
"""

import pytest
from unittest.mock import Mock, MagicMock
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory.store import MoorchehStore
from core.orchestration import OrchestrationEngine


@pytest.fixture
def mock_store():
    """Create a mocked MoorchehStore."""
    store = Mock(spec=MoorchehStore)
    store.connected = True
    store.store_record = Mock(return_value="test_record_id")
    store.query_similar = Mock(return_value=[])
    store.query_by_metadata = Mock(return_value=[])
    store.get_record = Mock(return_value=None)
    store.health_check = Mock(return_value={
        "connected": True,
        "fallback_available": True,
    })
    return store


@pytest.fixture
def orchestration_engine(mock_store):
    """Create an OrchestrationEngine instance."""
    engine = OrchestrationEngine(mock_store, "test-project")
    return engine


@pytest.fixture
def test_goal_id(orchestration_engine):
    """Create a test goal."""
    return orchestration_engine.create_goal("Test goal description")
