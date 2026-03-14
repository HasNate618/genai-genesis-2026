"""
Moorcheh client wrapper with full local JSON fallback.

Dependency order: schemas -> store
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import structlog

from src.config import Settings, get_settings
from src.memory.schemas import MemoryRecord, make_record_id, RecordType, RecordStatus

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Attempt to import the Moorcheh SDK; fall back gracefully if unavailable.
# ---------------------------------------------------------------------------
try:
    import moorcheh  # type: ignore

    _MOORCHEH_AVAILABLE = True
except ImportError:
    _MOORCHEH_AVAILABLE = False


# ---------------------------------------------------------------------------
# TF-IDF helpers for fallback similarity search
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _tf(tokens: list[str]) -> dict[str, float]:
    total = len(tokens) or 1
    counts: dict[str, int] = Counter(tokens)
    return {t: c / total for t, c in counts.items()}


def _cosine_sim(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    keys = set(vec_a) & set(vec_b)
    dot = sum(vec_a[k] * vec_b[k] for k in keys)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _similarity(text_a: str, text_b: str) -> float:
    tf_a = _tf(_tokenize(text_a))
    tf_b = _tf(_tokenize(text_b))
    return _cosine_sim(tf_a, tf_b)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _with_retry(fn, attempts: int = 3, base_delay: float = 0.5):
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait = base_delay * (2 ** attempt)
            logger.warning("retry", attempt=attempt + 1, error=str(exc), wait=wait)
            time.sleep(wait)
    raise RuntimeError(f"All {attempts} attempts failed") from last_exc


# ---------------------------------------------------------------------------
# Local JSON Fallback Store
# ---------------------------------------------------------------------------

class _FallbackStore:
    """Stores MemoryRecord objects as individual JSON files on disk."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, record_id: str) -> Path:
        safe = record_id.replace(":", "_").replace("/", "_")
        return self._base / f"{safe}.json"

    def upsert(self, record: MemoryRecord) -> None:
        data = asdict(record)
        self._path(record.id).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def get(self, record_id: str) -> MemoryRecord | None:
        p = self._path(record_id)
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        return MemoryRecord(**data)

    def delete(self, record_id: str) -> bool:
        p = self._path(record_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def list_all(self) -> list[MemoryRecord]:
        records = []
        for p in self._base.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                records.append(MemoryRecord(**data))
            except Exception:  # noqa: BLE001
                pass
        return records

    def similarity_search(
        self, query: str, top_k: int, filters: dict[str, Any]
    ) -> list[MemoryRecord]:
        candidates = self.list_all()
        candidates = _apply_filters(candidates, filters)
        scored = [(r, _similarity(query, r.text)) for r in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in scored[:top_k]]

    def list_records(self, filters: dict[str, Any]) -> list[MemoryRecord]:
        records = self.list_all()
        return _apply_filters(records, filters)

    def health_check(self) -> dict:
        return {"status": "ok", "backend": "local_fallback", "base_dir": str(self._base)}


def _apply_filters(records: list[MemoryRecord], filters: dict[str, Any]) -> list[MemoryRecord]:
    result = []
    for r in records:
        match = True
        for key, val in filters.items():
            record_val = getattr(r, key, None)
            if isinstance(val, list):
                if record_val not in val:
                    match = False
                    break
            else:
                if record_val != val:
                    match = False
                    break
        if match:
            result.append(r)
    return result


# ---------------------------------------------------------------------------
# Moorcheh Store
# ---------------------------------------------------------------------------

class MoorchehStore:
    """
    Thin abstraction over Moorcheh SDK with a full local JSON fallback.

    When the SDK is unavailable or MOORCHEH_API_KEY is empty, all operations
    are transparently served by _FallbackStore.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._use_fallback = (
            not _MOORCHEH_AVAILABLE
            or not self._settings.moorcheh_api_key
        )
        if self._use_fallback:
            self._fallback = _FallbackStore(self._settings.fallback_dir)
            logger.info("moorcheh_store.init", backend="local_fallback")
        else:
            self._client = moorcheh.Client(  # type: ignore[name-defined]
                api_key=self._settings.moorcheh_api_key,
                base_url=self._settings.moorcheh_base_url,
            )
            self._fallback = _FallbackStore(self._settings.fallback_dir)
            logger.info("moorcheh_store.init", backend="moorcheh_sdk")

    # ------------------------------------------------------------------
    # Namespace management
    # ------------------------------------------------------------------

    def namespace_setup(self, project_id: str) -> None:
        if self._use_fallback:
            ns_dir = self._settings.fallback_dir / project_id
            ns_dir.mkdir(parents=True, exist_ok=True)
            logger.info("namespace_setup.fallback", project_id=project_id)
            return
        for suffix in ("shared", f"ws-main"):
            ns_name = f"spm-{project_id}-{suffix}"
            try:
                def _create(name=ns_name):
                    self._client.namespaces.create(name=name, type="text")
                _with_retry(_create)
                logger.info("namespace_setup.created", namespace=ns_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("namespace_setup.skipped", namespace=ns_name, error=str(exc))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        log = logger.bind(record_id=record.id, record_type=record.record_type)
        if self._use_fallback:
            self._fallback.upsert(record)
            log.info("store.upsert.fallback")
            return record
        try:
            def _do():
                self._client.documents.upsert(
                    id=record.id,
                    text=record.text,
                    metadata={
                        "record_type": record.record_type,
                        "project_id": record.project_id,
                        "workspace_id": record.workspace_id,
                        "agent_id": record.agent_id,
                        "timestamp": record.timestamp,
                        "importance": record.importance,
                        "status": record.status,
                        "payload": json.dumps(record.payload),
                    },
                )
            _with_retry(_do)
            # Also keep local copy for fast structured access
            self._fallback.upsert(record)
            log.info("store.upsert.sdk")
        except Exception as exc:  # noqa: BLE001
            log.error("store.upsert.error", error=str(exc))
            self._fallback.upsert(record)
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        if self._use_fallback:
            return self._fallback.get(record_id)
        local = self._fallback.get(record_id)
        if local:
            return local
        try:
            def _do():
                return self._client.documents.get(id=record_id)
            doc = _with_retry(_do)
            meta = doc.metadata or {}
            payload = json.loads(meta.get("payload", "{}"))
            return MemoryRecord(
                id=record_id,
                record_type=meta.get("record_type", ""),
                project_id=meta.get("project_id", ""),
                workspace_id=meta.get("workspace_id", ""),
                agent_id=meta.get("agent_id", ""),
                timestamp=meta.get("timestamp", ""),
                text=doc.text,
                importance=int(meta.get("importance", 3)),
                status=meta.get("status", "open"),
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("store.get.error", record_id=record_id, error=str(exc))
            return None

    def delete(self, record_id: str) -> bool:
        deleted = self._fallback.delete(record_id)
        if self._use_fallback:
            return deleted
        try:
            def _do():
                self._client.documents.delete(id=record_id)
            _with_retry(_do)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("store.delete.error", record_id=record_id, error=str(exc))
            return False

    def similarity_search(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryRecord]:
        k = top_k or self._settings.top_k_search
        f = filters or {}
        if self._use_fallback:
            return self._fallback.similarity_search(query, k, f)
        try:
            def _do():
                return self._client.similarity_search.query(
                    query=query, top_k=k, filters=f
                )
            results = _with_retry(_do)
            records = []
            for doc in results:
                meta = doc.metadata or {}
                payload = json.loads(meta.get("payload", "{}"))
                records.append(
                    MemoryRecord(
                        id=doc.id,
                        record_type=meta.get("record_type", ""),
                        project_id=meta.get("project_id", ""),
                        workspace_id=meta.get("workspace_id", ""),
                        agent_id=meta.get("agent_id", ""),
                        timestamp=meta.get("timestamp", ""),
                        text=doc.text,
                        importance=int(meta.get("importance", 3)),
                        status=meta.get("status", "open"),
                        payload=payload,
                    )
                )
            return records
        except Exception as exc:  # noqa: BLE001
            logger.error("store.similarity_search.error", error=str(exc))
            return self._fallback.similarity_search(query, k, f)

    def list_records(self, filters: dict[str, Any] | None = None) -> list[MemoryRecord]:
        f = filters or {}
        if self._use_fallback:
            return self._fallback.list_records(f)
        # Fall back to local cache for structured listing
        return self._fallback.list_records(f)

    def health_check(self) -> dict:
        if self._use_fallback:
            return self._fallback.health_check()
        try:
            def _do():
                return self._client.health.check()
            result = _with_retry(_do)
            return {"status": "ok", "backend": "moorcheh_sdk", "detail": str(result)}
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "backend": "moorcheh_sdk", "error": str(exc)}
