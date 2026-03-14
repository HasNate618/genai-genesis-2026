"""
Shared pytest fixtures for the SPM test suite.

Provides:
  - ``index``   : in-memory SQLiteIndex
  - ``store``   : MemoryStore backed by a MockMoorchehClient (no network)
  - ``engine``  : CoordinationEngine wired to the above
  - ``detector``: ConflictDetector wired to the above
  - ``compactor``: Compactor wired to the above
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory.index import SQLiteIndex
from src.memory.store import MemoryStore
from src.core.coordination import CoordinationEngine
from src.core.conflict import ConflictDetector
from src.core.compactor import Compactor


# ── Mock Moorcheh client ──────────────────────────────────────────────────────


class MockMoorchehClient:
    """
    Minimal in-memory mock for the Moorcheh async SDK client.

    Stores documents in a dict keyed by (namespace, id).
    """

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], dict[str, Any]] = {}

        self.namespaces = MagicMock()
        self.namespaces.get = AsyncMock(return_value={"name": "mock"})
        self.namespaces.create = AsyncMock(return_value={"name": "mock"})

        self.documents = MagicMock()
        self.documents.upsert = AsyncMock(side_effect=self._upsert_doc)
        self.documents.get = AsyncMock(side_effect=self._get_doc)
        self.documents.delete = AsyncMock(side_effect=self._delete_doc)

        self.similarity_search = MagicMock()
        self.similarity_search.query = AsyncMock(return_value=[])

        self.answer = MagicMock()
        self.answer.generate = AsyncMock(
            return_value={"answer": "Mock answer", "citations": []}
        )

    async def _upsert_doc(self, namespace: str, id: str, text: str, metadata: dict) -> None:
        self._docs[(namespace, id)] = {"id": id, "text": text, **metadata}

    async def _get_doc(self, namespace: str, id: str) -> dict | None:
        return self._docs.get((namespace, id))

    async def _delete_doc(self, namespace: str, id: str) -> None:
        self._docs.pop((namespace, id), None)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def index() -> SQLiteIndex:
    return SQLiteIndex(db_path=":memory:")


@pytest.fixture
async def store(monkeypatch) -> MemoryStore:
    s = MemoryStore(project_id="test-project", workspace_id="test-ws")
    mock_client = MockMoorchehClient()
    s._client = mock_client
    s._moorcheh_available = True
    s._initialised = True
    return s


@pytest.fixture
async def engine(store, index) -> CoordinationEngine:
    return CoordinationEngine(store=store, index=index)


@pytest.fixture
async def detector(store, index) -> ConflictDetector:
    return ConflictDetector(store=store, index=index)


@pytest.fixture
async def compactor(store, index) -> Compactor:
    return Compactor(store=store, index=index)
