"""
Moorcheh client wrapper with offline JSON fallback.

Responsibilities:
  - Namespace lifecycle (create / ensure exists)
  - Document CRUD (upsert, get, delete)
  - Similarity search (semantic retrieval)
  - Grounded answer generation
  - Retry logic with exponential back-off
  - Transparent fallback to a local JSON store when the Moorcheh API is
    unreachable (writes are queued and replayed on reconnect)

Usage::

    from src.memory.store import MemoryStore
    store = MemoryStore(project_id="my-proj", workspace_id="main")
    await store.upsert(record)
    results = await store.search("session management auth", top_k=5)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from src.config import settings
from src.memory.schemas import MemoryRecord

logger = logging.getLogger(__name__)

# ── Namespace helpers ─────────────────────────────────────────────────────────


def _namespace_name(project_id: str, workspace_id: str) -> str:
    """Return the Moorcheh namespace name for a project+workspace combo."""
    return f"spm-{project_id}-{workspace_id}"


# ── Offline fallback ──────────────────────────────────────────────────────────


class _JSONFallbackStore:
    """Simple JSON-file-backed store used when Moorcheh is unreachable."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self._pending_writes: list[MemoryRecord] = []
        if self._path.exists():
            try:
                with open(self._path) as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def _save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    def upsert(self, namespace: str, record: MemoryRecord) -> None:
        self._data.setdefault(namespace, {})[record.id] = record.to_dict()
        self._save()
        self._pending_writes.append(record)

    def get(self, namespace: str, record_id: str) -> dict[str, Any] | None:
        return self._data.get(namespace, {}).get(record_id)

    def delete(self, namespace: str, record_id: str) -> None:
        self._data.get(namespace, {}).pop(record_id, None)
        self._save()

    def search(
        self, namespace: str, query: str, top_k: int
    ) -> list[dict[str, Any]]:
        """Naive keyword overlap search — only used as offline fallback."""
        ns_data = self._data.get(namespace, {})
        query_words = set(query.lower().split())

        def _score(doc: dict[str, Any]) -> int:
            text_words = set(doc.get("text", "").lower().split())
            return len(query_words & text_words)

        ranked = sorted(ns_data.values(), key=_score, reverse=True)
        return ranked[:top_k]

    def drain_pending(self) -> list[MemoryRecord]:
        pending = list(self._pending_writes)
        self._pending_writes.clear()
        return pending


# ── Main store ────────────────────────────────────────────────────────────────


class MemoryStore:
    """
    Thin abstraction over the Moorcheh SDK with retry logic and fallback.

    Parameters
    ----------
    project_id:
        Logical project identifier.  Used to build namespace names.
    workspace_id:
        Workspace/branch identifier.  Defaults to ``settings.default_workspace_id``.
    """

    _MAX_RETRIES = 3
    _RETRY_BASE_DELAY = 1.0  # seconds

    def __init__(
        self,
        project_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.project_id = project_id or settings.project_id
        self.workspace_id = workspace_id or settings.default_workspace_id
        self._namespace = _namespace_name(self.project_id, self.workspace_id)
        self._shared_namespace = _namespace_name(self.project_id, "shared")
        self._fallback = _JSONFallbackStore(settings.fallback_json_path)
        self._moorcheh_available = True
        self._client: Any = None  # lazy-initialised
        self._initialised = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialise(self) -> None:
        """Ensure namespaces exist.  Must be called before other operations."""
        if self._initialised:
            return
        try:
            client = await self._get_client()
            await self._ensure_namespace(client, self._namespace)
            await self._ensure_namespace(client, self._shared_namespace)
            self._initialised = True
            logger.info(
                "MemoryStore initialised (namespaces: %s, %s)",
                self._namespace,
                self._shared_namespace,
            )
        except Exception as exc:
            logger.warning(
                "Moorcheh unavailable during init (%s) — falling back to JSON store",
                exc,
            )
            self._moorcheh_available = False
            self._initialised = True

    async def _get_client(self) -> Any:
        """Lazy-initialise the Moorcheh SDK client."""
        if self._client is not None:
            return self._client
        try:
            import moorcheh  # type: ignore[import]

            self._client = moorcheh.AsyncClient(
                api_key=settings.moorcheh_api_key,
                base_url=settings.moorcheh_base_url,
            )
        except ImportError:
            raise RuntimeError(
                "moorcheh package is not installed.  Run: pip install moorcheh-sdk"
            )
        return self._client

    async def _ensure_namespace(self, client: Any, name: str) -> None:
        try:
            await client.namespaces.get(name)
        except Exception:
            await client.namespaces.create(name=name, type="text")
            logger.info("Created Moorcheh namespace: %s", name)

    # ── Write operations ──────────────────────────────────────────────────────

    async def upsert(
        self, record: MemoryRecord, use_shared: bool = False
    ) -> None:
        namespace = self._shared_namespace if use_shared else self._namespace
        doc = record.to_dict()
        if not self._moorcheh_available:
            self._fallback.upsert(namespace, record)
            return
        for attempt in range(self._MAX_RETRIES):
            try:
                client = await self._get_client()
                await client.documents.upsert(
                    namespace=namespace,
                    id=doc["id"],
                    text=doc["text"],
                    metadata={
                        k: v for k, v in doc.items() if k not in ("id", "text")
                    },
                )
                return
            except Exception as exc:
                if attempt == self._MAX_RETRIES - 1:
                    logger.error(
                        "Moorcheh upsert failed after %d retries: %s — using fallback",
                        self._MAX_RETRIES,
                        exc,
                    )
                    self._moorcheh_available = False
                    self._fallback.upsert(namespace, record)
                    return
                await asyncio.sleep(self._RETRY_BASE_DELAY * (2**attempt))

    async def delete(self, record_id: str, use_shared: bool = False) -> None:
        namespace = self._shared_namespace if use_shared else self._namespace
        if not self._moorcheh_available:
            self._fallback.delete(namespace, record_id)
            return
        try:
            client = await self._get_client()
            await client.documents.delete(namespace=namespace, id=record_id)
        except Exception as exc:
            logger.warning("Moorcheh delete failed: %s", exc)
            self._fallback.delete(namespace, record_id)

    # ── Read operations ───────────────────────────────────────────────────────

    async def get(
        self, record_id: str, use_shared: bool = False
    ) -> dict[str, Any] | None:
        namespace = self._shared_namespace if use_shared else self._namespace
        if not self._moorcheh_available:
            return self._fallback.get(namespace, record_id)
        try:
            client = await self._get_client()
            doc = await client.documents.get(namespace=namespace, id=record_id)
            return doc
        except Exception:
            return self._fallback.get(namespace, record_id)

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        use_shared: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Semantic similarity search against the namespace.

        Returns a list of document dicts ordered by relevance.
        """
        namespace = self._shared_namespace if use_shared else self._namespace
        k = top_k or settings.retrieval_top_k
        if not self._moorcheh_available:
            return self._fallback.search(namespace, query, k)
        try:
            client = await self._get_client()
            results = await client.similarity_search.query(
                namespace=namespace,
                query=query,
                top_k=k,
            )
            return results
        except Exception as exc:
            logger.warning("Moorcheh search failed: %s — using fallback", exc)
            return self._fallback.search(namespace, query, k)

    async def answer(
        self,
        question: str,
        top_k: int | None = None,
        use_shared: bool = False,
    ) -> dict[str, Any]:
        """
        Generate a grounded answer to ``question`` using Moorcheh's
        answer.generate endpoint.

        Returns a dict with keys ``answer`` and ``citations``.
        """
        namespace = self._shared_namespace if use_shared else self._namespace
        k = top_k or settings.retrieval_top_k
        if not self._moorcheh_available:
            docs = self._fallback.search(namespace, question, k)
            return {
                "answer": f"[Offline fallback] Retrieved {len(docs)} documents.",
                "citations": [d.get("id") for d in docs],
            }
        try:
            client = await self._get_client()
            result = await client.answer.generate(
                namespace=namespace,
                question=question,
                top_k=k,
            )
            return result
        except Exception as exc:
            logger.warning("Moorcheh answer failed: %s — using search fallback", exc)
            docs = await self.search(question, top_k=k, use_shared=use_shared)
            return {
                "answer": " ".join(d.get("text", "") for d in docs[:3]),
                "citations": [d.get("id") for d in docs],
            }

    # ── Reconnect / replay ────────────────────────────────────────────────────

    async def attempt_reconnect(self) -> bool:
        """
        Try to reconnect to Moorcheh and replay pending fallback writes.

        Returns True if reconnection succeeded.
        """
        try:
            client = await self._get_client()
            await self._ensure_namespace(client, self._namespace)
            self._moorcheh_available = True
            pending = self._fallback.drain_pending()
            for record in pending:
                await self.upsert(record)
            logger.info(
                "Moorcheh reconnected; replayed %d pending writes", len(pending)
            )
            return True
        except Exception as exc:
            logger.debug("Moorcheh reconnect failed: %s", exc)
            return False

    # ── Health ────────────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "moorcheh_available": self._moorcheh_available,
            "namespace": self._namespace,
        }
        if self._moorcheh_available:
            try:
                client = await self._get_client()
                await client.namespaces.get(self._namespace)
                result["namespace_exists"] = True
            except Exception as exc:
                result["namespace_exists"] = False
                result["error"] = str(exc)
        return result

    @property
    def is_available(self) -> bool:
        return self._moorcheh_available
