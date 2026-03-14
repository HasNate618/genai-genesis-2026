from backend.memory.schemas import ContextRecord, RecordType, WorkflowStage, build_record_id


def test_record_id_is_deterministic() -> None:
    first = build_record_id(workflow_id="wf-1", run_id="run-9", event_seq=3, record_type="task")
    second = build_record_id(workflow_id="wf-1", run_id="run-9", event_seq=3, record_type="task")
    assert first == second
    assert first == "wf:wf-1:run:run-9:evt:3:task"


def test_context_record_vector_payload_shape() -> None:
    record = ContextRecord(
        workflow_id="wf-1",
        run_id="run-1",
        event_seq=0,
        record_type=RecordType.PLAN,
        stage=WorkflowStage.PLANNING,
        status="done",
        raw_text="Planner generated a candidate implementation plan.",
        agent_id="planner",
    )
    payload = record.to_vector_payload(
        vector=[0.1, 0.2, 0.3],
        embedding_model="test-embed-v1",
        embedding_dimension=3,
    )

    assert payload["id"] == "wf:wf-1:run:run-1:evt:0:plan"
    assert payload["vector"] == [0.1, 0.2, 0.3]
    assert payload["embedding_model"] == "test-embed-v1"
    assert payload["embedding_dimension"] == 3
    assert payload["schema_version"] == "v1"

