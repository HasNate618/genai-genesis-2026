from typing import Any

from backend.config import Settings
from backend.memory.context_reader import WorkflowContextReader
from backend.memory.context_writer import WorkflowContextWriter
from backend.memory.embedding_provider import EmbeddingPayload, MockEmbeddingProvider
from backend.memory.moorcheh_client import MoorchehAPIError
from backend.memory.moorcheh_store import MoorchehVectorStore
from backend.memory.schemas import ContextRecord, RecordType, WorkflowStage


class FakeMoorchehClient:
    def __init__(self) -> None:
        self.uploaded: list[dict[str, Any]] = []

    def ensure_vector_namespace(self, *, namespace_name: str, vector_dimension: int) -> dict[str, Any]:
        return {
            "status": "created",
            "namespace_name": namespace_name,
            "vector_dimension": vector_dimension,
        }

    def health_check(self) -> dict[str, Any]:
        return {"status": "ok"}

    def upload_vectors(self, namespace_name: str, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        self.uploaded.extend(vectors)
        return {
            "status": "success",
            "namespace_name": namespace_name,
            "processed": len(vectors),
        }

    def search_vectors(
        self,
        *,
        namespaces: list[str],
        query_vector: list[float],
        top_k: int = 10,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        del namespaces, query_vector, threshold
        return {
            "results": [
                {"score": 0.91, "label": "Close Match", "metadata": payload}
                for payload in self.uploaded[:top_k]
            ]
        }


def _settings() -> Settings:
    return Settings(
        moorcheh_api_key="fake",
        moorcheh_base_url="https://api.moorcheh.ai/v1",
        moorcheh_vector_namespace="workflow-context-vectors",
        moorcheh_vector_dimension=8,
        embedding_provider="mock",
        embedding_model="mock-model",
        embedding_api_key="",
        embedding_base_url="",
        embedding_batch_size=8,
        retrieval_top_k=12,
        conflict_threshold=0.35,
        max_context_window=20,
    )


def test_write_then_read_planner_context_loop() -> None:
    settings = _settings()
    fake_client = FakeMoorchehClient()
    embedder = MockEmbeddingProvider(model_name="mock-model", dimension=8, batch_size=8)
    store = MoorchehVectorStore(settings=settings, client=fake_client, embedder=embedder)
    writer = WorkflowContextWriter(store)
    reader = WorkflowContextReader(store)

    store.provision_namespace()
    writer.write_event(
        workflow_id="wf-1",
        run_id="run-1",
        record_type=RecordType.PLAN,
        stage=WorkflowStage.PLANNING,
        status="done",
        raw_text="Approved plan routes auth and billing tasks to separate agents.",
        file_paths=["src/auth.py", "src/billing.py"],
        agent_id="planner",
        event_seq=0,
    )
    writer.write_event(
        workflow_id="wf-1",
        run_id="run-1",
        record_type=RecordType.CONFLICT,
        stage=WorkflowStage.COORDINATION,
        status="blocked",
        raw_text="Recent conflict on src/auth.py; avoid overlapping assignments.",
        file_paths=["src/auth.py"],
        conflict_score=0.7,
        agent_id="conflict-analyzer",
        event_seq=1,
    )

    bundle = reader.fetch_for_planner(
        workflow_id="wf-1",
        goal_text="Implement async planning with conflict-aware memory retrieval.",
        planned_files=["src/auth.py"],
    )

    assert len(bundle.records) >= 2
    assert "status(" in bundle.summary
    prompt = reader.format_for_prompt(bundle)
    assert "Retrieved workflow context" in prompt
    assert "src/auth.py" in prompt


def test_store_uses_search_document_and_search_query_input_types() -> None:
    class CaptureEmbedder:
        model_name = "capture"
        dimension = 8

        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def embed(self, texts: list[str], *, input_type: str | None = None) -> list[EmbeddingPayload]:
            self.calls.append(input_type)
            return [
                EmbeddingPayload(
                    text=text,
                    vector=[0.1] * self.dimension,
                    model=self.model_name,
                    dimension=self.dimension,
                )
                for text in texts
            ]

    settings = _settings()
    fake_client = FakeMoorchehClient()
    embedder = CaptureEmbedder()
    store = MoorchehVectorStore(settings=settings, client=fake_client, embedder=embedder)

    store.write_record(
        ContextRecord(
            workflow_id="wf-1",
            run_id="run-1",
            event_seq=0,
            record_type=RecordType.PLAN,
            stage=WorkflowStage.PLANNING,
            status="done",
            raw_text="Plan text",
        )
    )
    store.search_context(query_text="Where did auth conflicts happen?")

    assert embedder.calls == ["search_document", "search_query"]


def test_provision_namespace_falls_back_on_dimension_mismatch() -> None:
    class MismatchClient(FakeMoorchehClient):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        def ensure_vector_namespace(self, *, namespace_name: str, vector_dimension: int) -> dict[str, Any]:
            self.calls.append(namespace_name)
            if namespace_name == "workflow-context-vectors":
                raise MoorchehAPIError(
                    "Namespace exists with mismatched vector dimension. Expected 1024, got 1536."
                )
            return {
                "status": "created",
                "namespace_name": namespace_name,
                "vector_dimension": vector_dimension,
            }

    settings = Settings(
        moorcheh_api_key="fake",
        moorcheh_base_url="https://api.moorcheh.ai/v1",
        moorcheh_vector_namespace="workflow-context-vectors",
        moorcheh_vector_dimension=1024,
        embedding_provider="cohere",
        embedding_model="embed-english-v3.0",
        embedding_api_key="cohere-key",
        embedding_base_url="https://api.cohere.ai",
        embedding_batch_size=8,
        retrieval_top_k=12,
        conflict_threshold=0.35,
        max_context_window=20,
    )
    client = MismatchClient()
    embedder = MockEmbeddingProvider(model_name="mock-model", dimension=1024, batch_size=8)
    store = MoorchehVectorStore(settings=settings, client=client, embedder=embedder)

    result = store.provision_namespace()

    assert client.calls == ["workflow-context-vectors", "workflow-context-vectors-1024"]
    assert store.settings.moorcheh_vector_namespace == "workflow-context-vectors-1024"
    assert result["namespace_fallback_reason"] == "dimension_mismatch"
