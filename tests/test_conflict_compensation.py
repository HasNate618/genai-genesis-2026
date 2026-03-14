from backend.config import Settings
from backend.memory.conflict_context import ConflictCompensator, TaskDraft


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
        retrieval_top_k=10,
        conflict_threshold=0.35,
        max_context_window=20,
    )


def test_compensation_serializes_overlapping_tasks_on_hot_file() -> None:
    compensator = ConflictCompensator(settings=_settings())
    tasks = [
        TaskDraft(task_id="task-1", agent_id="a1", file_paths=["src/auth.py", "src/api.py"]),
        TaskDraft(task_id="task-2", agent_id="a2", file_paths=["src/auth.py"]),
    ]
    history = [
        {
            "metadata": {
                "stage": "merge",
                "status": "failed",
                "file_paths": ["src/auth.py"],
                "conflict_score": 0.8,
            }
        }
    ]

    result = compensator.compensate(tasks=tasks, context_records=history)

    by_task = {task.task_id: task for task in result.adjusted_tasks}
    assert "task-1" in by_task["task-2"].depends_on
    assert by_task["task-2"].parallelizable is False
    assert result.conflict_signals

