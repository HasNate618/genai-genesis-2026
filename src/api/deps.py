"""
FastAPI dependency injection helpers.

Provides cached singletons for MemoryStore, SQLiteIndex,
CoordinationEngine, ConflictDetector, and Compactor.
"""

from __future__ import annotations

import functools
from typing import Any

from src.config import settings
from src.core.compactor import Compactor
from src.core.conflict import ConflictDetector
from src.core.coordination import CoordinationEngine
from src.memory.index import SQLiteIndex
from src.memory.store import MemoryStore


@functools.lru_cache(maxsize=1)
def get_store() -> MemoryStore:
    return MemoryStore(
        project_id=settings.project_id,
        workspace_id=settings.default_workspace_id,
    )


@functools.lru_cache(maxsize=1)
def get_index() -> SQLiteIndex:
    return SQLiteIndex(db_path=settings.sqlite_path)


@functools.lru_cache(maxsize=1)
def get_engine() -> CoordinationEngine:
    return CoordinationEngine(store=get_store(), index=get_index())


@functools.lru_cache(maxsize=1)
def get_detector() -> ConflictDetector:
    return ConflictDetector(store=get_store(), index=get_index())


@functools.lru_cache(maxsize=1)
def get_compactor() -> Compactor:
    return Compactor(store=get_store(), index=get_index())
