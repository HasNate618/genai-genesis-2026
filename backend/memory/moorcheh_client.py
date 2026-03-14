"""Minimal Moorcheh API client with retry/backoff for orchestration memory."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from backend.config import Settings


class MoorchehAPIError(RuntimeError):
    """Raised when Moorcheh API calls fail."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    initial_backoff_seconds: float = 0.4
    backoff_multiplier: float = 2.0


class MoorchehClient:
    """REST client for Moorcheh namespace/data/search operations."""

    def __init__(self, settings: Settings, retry_policy: RetryPolicy | None = None) -> None:
        self._base_url = settings.moorcheh_base_url.rstrip("/")
        self._api_key = settings.moorcheh_api_key
        self._retry = retry_policy or RetryPolicy()

    def list_namespaces(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/namespaces")
        # API shape may be list directly or wrapped.
        if isinstance(response, list):
            return response
        namespaces = response.get("namespaces", [])
        if not isinstance(namespaces, list):
            raise MoorchehAPIError("Unexpected namespaces response shape.")
        return namespaces

    def create_vector_namespace(self, namespace_name: str, vector_dimension: int) -> dict[str, Any]:
        payload = {
            "namespace_name": namespace_name,
            "type": "vector",
            "vector_dimension": vector_dimension,
        }
        return self._request("POST", "/namespaces", payload)

    def ensure_vector_namespace(
        self, *, namespace_name: str, vector_dimension: int
    ) -> dict[str, Any]:
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
        created = self.create_vector_namespace(namespace_name, vector_dimension)
        return {"status": "created", "namespace_name": namespace_name, "result": created}

    def upload_vectors(self, namespace_name: str, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"vectors": vectors}
        return self._request("POST", f"/namespaces/{namespace_name}/vectors", payload)

    def search_vectors(
        self,
        *,
        namespaces: list[str],
        query_vector: list[float],
        top_k: int = 10,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query_vector,
            "namespaces": namespaces,
            "top_k": top_k,
        }
        if threshold is not None:
            payload["threshold"] = threshold
        return self._request("POST", "/search", payload)

    def generate_answer(
        self,
        *,
        namespace: str,
        query: str,
        top_k: int = 5,
        temperature: float = 0.3,
        namespace_type: str = "vector",
    ) -> dict[str, Any]:
        payload = {
            "namespace": namespace,
            "query": query,
            "top_k": top_k,
            "temperature": temperature,
            "type": namespace_type,
        }
        return self._request("POST", "/answer", payload)

    def health_check(self) -> dict[str, Any]:
        """Performs a lightweight health check by listing namespaces."""
        namespaces = self.list_namespaces()
        return {"status": "ok", "namespace_count": len(namespaces)}

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self._base_url}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")

        backoff = self._retry.initial_backoff_seconds
        last_error: Exception | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            req = request.Request(
                url,
                method=method.upper(),
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self._api_key,
                },
            )
            try:
                with request.urlopen(req, timeout=30) as response:
                    raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = MoorchehAPIError(f"{method} {path} failed: HTTP {exc.code} {detail}")
                is_retryable = exc.code in (429, 500, 502, 503, 504)
                if not is_retryable or attempt == self._retry.max_attempts:
                    raise last_error from exc
            except error.URLError as exc:
                last_error = MoorchehAPIError(f"{method} {path} connection error: {exc}")
                if attempt == self._retry.max_attempts:
                    raise last_error from exc

            time.sleep(backoff)
            backoff *= self._retry.backoff_multiplier

        if last_error:
            raise last_error
        raise MoorchehAPIError(f"{method} {path} failed for unknown reason.")

