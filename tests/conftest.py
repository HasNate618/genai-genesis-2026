"""
Shared pytest fixtures.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from src.config import Settings
from src.memory.store import MoorchehStore
from src.memory.index import SQLiteIndex
from src.memory.schemas import (
    MemoryRecord,
    RecordType,
    RecordStatus,
    make_record_id,
)
from src.core.coordination import CoordinationEngine
from src.core.conflict import ConflictDetector
from src.core.compactor import CompactionWorker


@pytest.fixture
def mock_settings(tmp_path: Path) -> Settings:
    return Settings(
        MOORCHEH_API_KEY="",
        MOORCHEH_BASE_URL="http://localhost:9999",
        SPM_PROJECT_ID="test-project",
        SPM_LOG_LEVEL="DEBUG",
        OPENAI_API_KEY="",
        LLM_PROVIDER="local",
        COMPACTION_THRESHOLD=10,
        COMPACTION_IMPORTANCE_MAX=3,
        SQLITE_PATH=tmp_path / "test.db",
        FALLBACK_DIR=tmp_path / "fallback",
        API_HOST="127.0.0.1",
        API_PORT=8001,
        TOP_K_SEARCH=3,
    )


@pytest.fixture
def mock_store(mock_settings: Settings) -> MoorchehStore:
    store = MoorchehStore(settings=mock_settings)
    return store


@pytest.fixture
def mock_index(mock_settings: Settings) -> SQLiteIndex:
    index = SQLiteIndex(settings=mock_settings, db_path=":memory:")
    index.initialize()
    return index


@pytest.fixture
def mock_engine(
    mock_store: MoorchehStore,
    mock_index: SQLiteIndex,
    mock_settings: Settings,
) -> CoordinationEngine:
    return CoordinationEngine(
        store=mock_store, index=mock_index, settings=mock_settings
    )


@pytest.fixture
def mock_detector(
    mock_store: MoorchehStore, mock_index: SQLiteIndex
) -> ConflictDetector:
    return ConflictDetector(store=mock_store, index=mock_index)


@pytest.fixture
def mock_compactor(
    mock_store: MoorchehStore,
    mock_index: SQLiteIndex,
    mock_settings: Settings,
) -> CompactionWorker:
    return CompactionWorker(
        store=mock_store, index=mock_index, settings=mock_settings
    )


@pytest.fixture
def sample_task_claim_record() -> MemoryRecord:
    rid = make_record_id(RecordType.task_claim.value, "test-project")
    return MemoryRecord(
        id=rid,
        record_type=RecordType.task_claim.value,
        project_id="test-project",
        workspace_id="shared",
        agent_id="agent-x",
        timestamp="2024-01-01T00:00:00+00:00",
        text="Task claim by agent-x: refactor auth module. Files: login.py, session.py",
        importance=4,
        status=RecordStatus.open.value,
        payload={
            "task_description": "Refactor auth module",
            "file_paths": ["login.py", "session.py"],
            "dependencies": [],
            "task_id": rid,
        },
    )


@pytest.fixture
def async_client(mock_settings: Settings):
    """FastAPI TestClient with overridden dependencies."""
    from fastapi.testclient import TestClient
    from src.api.server import app
    from src.api import deps

    # Override singletons with test instances
    store = MoorchehStore(settings=mock_settings)
    index = SQLiteIndex(settings=mock_settings, db_path=":memory:")
    index.initialize()
    engine = CoordinationEngine(store=store, index=index, settings=mock_settings)
    detector = ConflictDetector(store=store, index=index)
    compactor = CompactionWorker(store=store, index=index, settings=mock_settings)
    from src.metrics.collector import MetricsCollector
    metrics = MetricsCollector()

    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_index] = lambda: index
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_detector] = lambda: detector
    app.dependency_overrides[deps.get_compactor] = lambda: compactor
    app.dependency_overrides[deps.get_metrics] = lambda: metrics

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
