"""
FastAPI dependency injection singletons.
"""

from __future__ import annotations

from functools import lru_cache

from src.config import get_settings
from src.memory.store import MoorchehStore
from src.memory.index import SQLiteIndex
from src.core.coordination import CoordinationEngine
from src.core.conflict import ConflictDetector
from src.core.compactor import CompactionWorker
from src.metrics.collector import MetricsCollector


@lru_cache(maxsize=1)
def get_store() -> MoorchehStore:
    settings = get_settings()
    store = MoorchehStore(settings=settings)
    store.namespace_setup(settings.spm_project_id)
    return store


@lru_cache(maxsize=1)
def get_index() -> SQLiteIndex:
    settings = get_settings()
    index = SQLiteIndex(settings=settings)
    index.initialize()
    return index


@lru_cache(maxsize=1)
def get_engine() -> CoordinationEngine:
    return CoordinationEngine(
        store=get_store(),
        index=get_index(),
        settings=get_settings(),
    )


@lru_cache(maxsize=1)
def get_detector() -> ConflictDetector:
    return ConflictDetector(store=get_store(), index=get_index())


@lru_cache(maxsize=1)
def get_compactor() -> CompactionWorker:
    return CompactionWorker(
        store=get_store(),
        index=get_index(),
        settings=get_settings(),
    )


@lru_cache(maxsize=1)
def get_metrics() -> MetricsCollector:
    return MetricsCollector()
