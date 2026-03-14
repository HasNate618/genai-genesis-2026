"""Moorcheh API client wrapper using official moorcheh-sdk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moorcheh_sdk import MoorchehClient as _MoorchehSDKClient

from backend.config import Settings


class MoorchehAPIError(RuntimeError):
    """Raised when Moorcheh API calls fail."""


@dataclass(frozen=True)
class RetryPolicy:
    """Retry configuration (SDK handles retries internally)."""

    max_attempts: int = 4
    initial_backoff_seconds: float = 0.4
    backoff_multiplier: float = 2.0


class MoorchehClient:
    """Wrapper for Moorcheh API operations using the official SDK."""

    def __init__(self, settings: Settings, retry_policy: RetryPolicy | None = None) -> None:
        self._sdk_client = _MoorchehSDKClient(api_key=settings.moorcheh_api_key)
        self._retry = retry_policy or RetryPolicy()

    def list_namespaces(self) -> list[dict[str, Any]]:
        """List all vector namespaces."""
        try:
            response = self._sdk_client.namespaces.list()
            # SDK returns a dict-like response; extract namespaces list
            if isinstance(response, dict):
                namespaces = response.get("namespaces", [])
            elif isinstance(response, list):
                namespaces = response
            else:
                # Handle other response shapes
                namespaces = list(response) if hasattr(response, "__iter__") else []
            return namespaces if isinstance(namespaces, list) else []
        except Exception as exc:
            raise MoorchehAPIError(f"Failed to list namespaces: {exc}") from exc

    def create_vector_namespace(self, namespace_name: str, vector_dimension: int) -> dict[str, Any]:
        """Create a vector namespace."""
        try:
            result = self._sdk_client.namespaces.create(
                namespace_name=namespace_name,
                type="vector",
                vector_dimension=vector_dimension,
            )
            return result if isinstance(result, dict) else {"status": "created"}
        except Exception as exc:
            raise MoorchehAPIError(f"Failed to create namespace {namespace_name}: {exc}") from exc

    def ensure_vector_namespace(
        self, *, namespace_name: str, vector_dimension: int
    ) -> dict[str, Any]:
        """Ensure a vector namespace exists with correct dimension."""
        try:
            existing = self.list_namespaces()
            for namespace in existing:
                if namespace.get("namespace_name") == namespace_name:
                    existing_dim = namespace.get("vector_dimension")
                    if existing_dim and int(existing_dim) != vector_dimension:
                        raise MoorchehAPIError(
                            "Namespace exists with mismatched vector dimension. "
                            f"Expected {vector_dimension}, got {existing_dim}."
                        )
                    return {
                        "status": "exists",
                        "namespace_name": namespace_name,
                        "vector_dimension": vector_dimension,
                    }
            # Create if not found
            created = self.create_vector_namespace(namespace_name, vector_dimension)
            return {"status": "created", "namespace_name": namespace_name, "result": created}
        except MoorchehAPIError:
            raise
        except Exception as exc:
            raise MoorchehAPIError(f"Failed to ensure namespace {namespace_name}: {exc}") from exc

    def upload_vectors(self, namespace_name: str, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        """Upload vectors to a namespace."""
        try:
            result = self._sdk_client.vectors.upload(
                namespace_name=namespace_name,
                vectors=vectors,
            )
            return result if isinstance(result, dict) else {"status": "success"}
        except Exception as exc:
            raise MoorchehAPIError(
                f"Failed to upload {len(vectors)} vectors to {namespace_name}: {exc}"
            ) from exc

    def search_vectors(
        self,
        *,
        namespaces: list[str],
        query_vector: list[float],
        top_k: int = 10,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """Search for vectors in namespaces."""
        try:
            # Use query as a vector (list[float])
            result = self._sdk_client.search(
                namespaces=namespaces,
                query=query_vector,
                top_k=top_k,
                threshold=threshold or 0.25,
            )
            return result if isinstance(result, dict) else {"results": []}
        except Exception as exc:
            raise MoorchehAPIError(
                f"Failed to search in namespaces {namespaces}: {exc}"
            ) from exc

    def generate_answer(
        self,
        *,
        namespace: str,
        query: str,
        top_k: int = 5,
        temperature: float = 0.3,
        namespace_type: str = "vector",
    ) -> dict[str, Any]:
        """Generate an answer using RAG."""
        try:
            result = self._sdk_client.answer(
                namespace=namespace,
                query=query,
                top_k=top_k,
                temperature=temperature,
            )
            return result if isinstance(result, dict) else {"answer": ""}
        except Exception as exc:
            raise MoorchehAPIError(f"Failed to generate answer for query: {exc}") from exc

    def health_check(self) -> dict[str, Any]:
        """Performs a lightweight health check by listing namespaces."""
        try:
            namespaces = self.list_namespaces()
            return {"status": "ok", "namespace_count": len(namespaces)}
        except Exception as exc:
            raise MoorchehAPIError(f"Health check failed: {exc}") from exc
