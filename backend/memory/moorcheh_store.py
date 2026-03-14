"""Vector store facade for writing and retrieving workflow context from Moorcheh."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.config import Settings, get_settings
from backend.memory.embedding_provider import EmbeddingProvider, build_embedding_provider
from backend.memory.moorcheh_client import MoorchehClient
from backend.memory.schemas import ContextRecord
from backend.memory.telemetry import MemoryTelemetry, elapsed_timer


class MoorchehVectorStore:
    """Coordinates embedding generation and Moorcheh vector operations."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: MoorchehClient | None = None,
        embedder: EmbeddingProvider | None = None,
        telemetry: MemoryTelemetry | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or MoorchehClient(self.settings)
        self.embedder = embedder or build_embedding_provider(self.settings)
        self.telemetry = telemetry or MemoryTelemetry()

    def provision_namespace(self) -> dict[str, Any]:
        """Ensures the configured vector namespace exists with expected dimension."""
        try:
            result = self.client.ensure_vector_namespace(
                namespace_name=self.settings.moorcheh_vector_namespace,
                vector_dimension=self.settings.moorcheh_vector_dimension,
            )
            self.telemetry.record_provision()
            return result
        except Exception as exc:
            self.telemetry.record_error(str(exc))
            raise

    def health_check(self) -> dict[str, Any]:
        """Health check for diagnostics endpoints."""
        try:
            health = self.client.health_check()
            health["namespace"] = self.settings.moorcheh_vector_namespace
            health["telemetry"] = self.telemetry.snapshot()
            self.telemetry.record_health()
            return health
        except Exception as exc:
            self.telemetry.record_error(str(exc))
            raise

    def write_record(self, record: ContextRecord) -> dict[str, Any]:
        """Embeds and uploads a single context record."""
        try:
            with elapsed_timer() as elapsed:
                payload = self._build_vector_payloads([record])[0]
                result = self.client.upload_vectors(
                    self.settings.moorcheh_vector_namespace, [payload]
                )
            self.telemetry.record_write(count=1, elapsed_seconds=elapsed())
            return result
        except Exception as exc:
            self.telemetry.record_error(str(exc))
            raise

    def write_records(self, records: Iterable[ContextRecord]) -> dict[str, Any]:
        """Embeds and uploads many records in one call."""
        record_list = list(records)
        if not record_list:
            return {"status": "noop", "uploaded": 0}
        try:
            with elapsed_timer() as elapsed:
                payloads = self._build_vector_payloads(record_list)
                result = self.client.upload_vectors(self.settings.moorcheh_vector_namespace, payloads)
                result["uploaded"] = len(payloads)
            self.telemetry.record_write(count=len(payloads), elapsed_seconds=elapsed())
            return result
        except Exception as exc:
            self.telemetry.record_error(str(exc))
            raise

    def search_context(
        self,
        *,
        query_text: str,
        top_k: int | None = None,
        threshold: float | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves relevant context records for planning/coordinating agents."""
        try:
            with elapsed_timer() as elapsed:
                query_embedding = self.embedder.embed([query_text])[0]
                response = self.client.search_vectors(
                    namespaces=[self.settings.moorcheh_vector_namespace],
                    query_vector=query_embedding.vector,
                    top_k=top_k or self.settings.retrieval_top_k,
                    threshold=threshold,
                )
                results = response.get("results", [])
                if metadata_filters:
                    results = [
                        row
                        for row in results
                        if _matches_filters(row.get("metadata", row), metadata_filters)
                    ]
                windowed = results[: self.settings.max_context_window]
            self.telemetry.record_search(count=len(windowed), elapsed_seconds=elapsed())
            return windowed
        except Exception as exc:
            self.telemetry.record_error(str(exc))
            raise

    def _build_vector_payloads(self, records: list[ContextRecord]) -> list[dict[str, Any]]:
        embedding_payloads = self.embedder.embed([record.raw_text for record in records])
        payloads: list[dict[str, Any]] = []
        for record, embedding in zip(records, embedding_payloads):
            payloads.append(
                record.to_vector_payload(
                    vector=embedding.vector,
                    embedding_model=embedding.model,
                    embedding_dimension=embedding.dimension,
                )
            )
        return payloads


def _matches_filters(candidate: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        actual = candidate.get(key)
        if isinstance(expected, list):
            if isinstance(actual, list):
                if not any(item in actual for item in expected):
                    return False
            else:
                if actual not in expected:
                    return False
            continue
        if actual != expected:
            return False
    return True
