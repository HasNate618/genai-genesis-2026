import json

import pytest

from backend.config import Settings
from backend.memory.embedding_provider import (
    CohereEmbeddingProvider,
    EmbeddingPayload,
    OpenAICompatibleEmbeddingProvider,
    build_embedding_provider,
)


def _base_settings(**overrides: object) -> Settings:
    values = {
        "moorcheh_api_key": "fake",
        "moorcheh_base_url": "https://api.moorcheh.ai/v1",
        "moorcheh_vector_namespace": "workflow-context-vectors",
        "moorcheh_vector_dimension": 1024,
        "embedding_provider": "mock",
        "embedding_model": "mock-model",
        "embedding_api_key": "",
        "embedding_base_url": "",
        "embedding_batch_size": 8,
        "retrieval_top_k": 12,
        "conflict_threshold": 0.35,
        "max_context_window": 20,
    }
    values.update(overrides)
    return Settings(**values)


def test_build_embedding_provider_supports_cohere() -> None:
    settings = _base_settings(
        embedding_provider="cohere",
        embedding_model="embed-english-v3.0",
        embedding_api_key="cohere-key",
        embedding_base_url="https://api.cohere.ai",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, CohereEmbeddingProvider)
    assert provider.endpoint == "https://api.cohere.ai/v1/embed"


def test_build_embedding_provider_supports_openai_compatible() -> None:
    settings = _base_settings(
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_api_key="openai-key",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)


def test_cohere_provider_sends_input_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"embeddings": [[0.1, 0.2]]}).encode("utf-8")

    def _fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        del timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr("backend.memory.embedding_provider.request.urlopen", _fake_urlopen)

    provider = CohereEmbeddingProvider(
        api_key="cohere-key",
        model_name="embed-english-v3.0",
        dimension=2,
        batch_size=8,
        base_url="https://api.cohere.ai",
    )
    payloads = provider.embed(["hello"], input_type="search_query")

    assert len(payloads) == 1
    assert isinstance(payloads[0], EmbeddingPayload)
    assert captured["body"] == {
        "model": "embed-english-v3.0",
        "texts": ["hello"],
        "input_type": "search_query",
    }
