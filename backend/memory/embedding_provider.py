"""Embedding providers for vector-only workflow context retrieval."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, Sequence
from urllib import error, request

from backend.config import Settings


class EmbeddingProviderError(RuntimeError):
    """Raised when embedding generation fails."""


class EmbeddingDimensionError(EmbeddingProviderError):
    """Raised when generated vectors do not match configured dimensions."""


@dataclass(frozen=True)
class EmbeddingPayload:
    """Embedding plus model metadata for storage and diagnostics."""

    text: str
    vector: list[float]
    model: str
    dimension: int


class EmbeddingProvider(Protocol):
    """Protocol for embedding implementations."""

    model_name: str
    dimension: int

    def embed(
        self, texts: Sequence[str], *, input_type: str | None = None
    ) -> list[EmbeddingPayload]:
        """Converts source texts into vectors."""


def _normalize_vector(vector: list[float], *, expected_dim: int) -> list[float]:
    if len(vector) != expected_dim:
        raise EmbeddingDimensionError(
            f"Vector dimension mismatch. Expected {expected_dim}, got {len(vector)}."
        )
    return vector


def _chunked(values: Sequence[str], size: int) -> list[Sequence[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


class MockEmbeddingProvider:
    """Deterministic provider for local development and tests."""

    def __init__(self, *, model_name: str, dimension: int, batch_size: int) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size

    def embed(
        self, texts: Sequence[str], *, input_type: str | None = None
    ) -> list[EmbeddingPayload]:
        del input_type
        payloads: list[EmbeddingPayload] = []
        for text in texts:
            vector = self._deterministic_vector(text)
            payloads.append(
                EmbeddingPayload(
                    text=text,
                    vector=_normalize_vector(vector, expected_dim=self.dimension),
                    model=self.model_name,
                    dimension=self.dimension,
                )
            )
        return payloads

    def _deterministic_vector(self, text: str) -> list[float]:
        vector: list[float] = []
        seed = 0
        while len(vector) < self.dimension:
            digest = hashlib.sha256(f"{self.model_name}|{seed}|{text}".encode("utf-8")).digest()
            for i in range(0, len(digest), 4):
                if len(vector) == self.dimension:
                    break
                raw_int = int.from_bytes(digest[i : i + 4], byteorder="big", signed=False)
                vector.append((raw_int / 2**32) * 2.0 - 1.0)
            seed += 1
        return vector


class OpenAICompatibleEmbeddingProvider:
    """OpenAI-compatible embedding provider (OpenAI and compatible gateways)."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        dimension: int,
        batch_size: int,
        base_url: str = "",
    ) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size
        self.api_key = api_key
        self.endpoint = base_url.rstrip("/") or "https://api.openai.com/v1/embeddings"

    def embed(
        self, texts: Sequence[str], *, input_type: str | None = None
    ) -> list[EmbeddingPayload]:
        del input_type
        if not texts:
            return []

        payloads: list[EmbeddingPayload] = []
        for batch in _chunked(texts, self.batch_size):
            embeddings = self._embed_batch(batch)
            for source_text, vector in zip(batch, embeddings):
                payloads.append(
                    EmbeddingPayload(
                        text=source_text,
                        vector=_normalize_vector(vector, expected_dim=self.dimension),
                        model=self.model_name,
                        dimension=self.dimension,
                    )
                )
        return payloads

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model_name, "input": list(texts)}).encode("utf-8")
        req = request.Request(
            self.endpoint,
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingProviderError(
                f"Embedding API HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise EmbeddingProviderError(f"Embedding API connection error: {exc}") from exc

        try:
            parsed = json.loads(raw)
            data = parsed["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EmbeddingProviderError("Embedding API returned invalid response payload.") from exc

        vectors: list[list[float]] = []
        for item in data:
            vector = item.get("embedding")
            if not isinstance(vector, list):
                raise EmbeddingProviderError("Embedding API response missing 'embedding' list.")
            vectors.append([float(v) for v in vector])
        return vectors


class CohereEmbeddingProvider:
    """Cohere embedding provider."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        dimension: int,
        batch_size: int,
        base_url: str = "",
    ) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size
        self.api_key = api_key
        self.endpoint = self._resolve_endpoint(base_url)

    def _resolve_endpoint(self, base_url: str) -> str:
        if not base_url:
            return "https://api.cohere.ai/v1/embed"
        trimmed = base_url.rstrip("/")
        if trimmed.endswith("/embed"):
            return trimmed
        if trimmed.endswith("/v1"):
            return f"{trimmed}/embed"
        return f"{trimmed}/v1/embed"

    def embed(
        self, texts: Sequence[str], *, input_type: str | None = None
    ) -> list[EmbeddingPayload]:
        if not texts:
            return []

        payloads: list[EmbeddingPayload] = []
        resolved_input_type = input_type or "search_document"
        for batch in _chunked(texts, self.batch_size):
            embeddings = self._embed_batch(batch, input_type=resolved_input_type)
            for source_text, vector in zip(batch, embeddings):
                payloads.append(
                    EmbeddingPayload(
                        text=source_text,
                        vector=_normalize_vector(vector, expected_dim=self.dimension),
                        model=self.model_name,
                        dimension=self.dimension,
                    )
                )
        return payloads

    def _embed_batch(self, texts: Sequence[str], *, input_type: str) -> list[list[float]]:
        body = json.dumps(
            {"model": self.model_name, "texts": list(texts), "input_type": input_type}
        ).encode("utf-8")
        req = request.Request(
            self.endpoint,
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingProviderError(f"Cohere embed HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise EmbeddingProviderError(f"Cohere embed connection error: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EmbeddingProviderError("Cohere embed returned invalid JSON.") from exc

        raw_embeddings = parsed.get("embeddings")
        if isinstance(raw_embeddings, dict):
            vectors_any = raw_embeddings.get("float")
            if not isinstance(vectors_any, list):
                raise EmbeddingProviderError(
                    "Cohere embed response missing embeddings.float list."
                )
        elif isinstance(raw_embeddings, list):
            vectors_any = raw_embeddings
        else:
            raise EmbeddingProviderError("Cohere embed response missing embeddings list.")

        vectors: list[list[float]] = []
        for vector in vectors_any:
            if not isinstance(vector, list):
                raise EmbeddingProviderError("Cohere embed returned a non-list embedding vector.")
            vectors.append([float(v) for v in vector])

        if len(vectors) != len(texts):
            raise EmbeddingProviderError(
                f"Cohere embed vector count mismatch. Expected {len(texts)}, got {len(vectors)}."
            )
        return vectors


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Builds the configured embedding provider."""
    provider = settings.embedding_provider.lower()
    if provider == "mock":
        return MockEmbeddingProvider(
            model_name=settings.embedding_model,
            dimension=settings.moorcheh_vector_dimension,
            batch_size=settings.embedding_batch_size,
        )
    if provider == "openai":
        return OpenAICompatibleEmbeddingProvider(
            api_key=settings.embedding_api_key,
            model_name=settings.embedding_model,
            dimension=settings.moorcheh_vector_dimension,
            batch_size=settings.embedding_batch_size,
            base_url=settings.embedding_base_url,
        )
    if provider == "cohere":
        return CohereEmbeddingProvider(
            api_key=settings.embedding_api_key,
            model_name=settings.embedding_model,
            dimension=settings.moorcheh_vector_dimension,
            batch_size=settings.embedding_batch_size,
            base_url=settings.embedding_base_url,
        )
    raise EmbeddingProviderError(
        f"Unsupported EMBEDDING_PROVIDER '{settings.embedding_provider}'. "
        "Supported providers: mock, openai, cohere."
    )
