from typing import Any

from backend.config import Settings
from backend.memory.context_reader import WorkflowContextReader
from backend.memory.context_writer import WorkflowContextWriter
from backend.memory.embedding_provider import MockEmbeddingProvider
from backend.memory.moorcheh_store import MoorchehVectorStore
from backend.memory.schemas import RecordType, WorkflowStage


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

