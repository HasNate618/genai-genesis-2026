from backend.agents.context_contract import build_async_agent_context, parse_async_agent_context
from backend.memory.conflict_context import ConflictSignal, TaskDraft
from backend.memory.context_reader import ContextBundle


def test_async_agent_context_roundtrip() -> None:
    bundle = ContextBundle(
        query_text="planner objective: split auth tasks safely",
        records=[{"metadata": {"task_id": "task-1", "status": "blocked"}}],
        summary="status(blocked:1) stage(coordination:1)",
    )
    task = TaskDraft(task_id="task-2", agent_id="coder-2", file_paths=["src/auth.py"])
    signal = ConflictSignal(
        kind="file_overlap",
        file_path="src/auth.py",
        score=0.8,
        source_task_ids=["task-1", "task-2"],
        reason="Overlapping files",
    )

    context = build_async_agent_context(
        workflow_id="wf-42",
        run_id="run-9",
        agent_id="planner",
        objective="Create revised plan with reduced overlaps.",
        stage="planning",
        context_bundle=bundle,
        assigned_tasks=[task],
        conflict_signals=[signal],
        constraints=["Keep task-2 after task-1"],
    )
    parsed = parse_async_agent_context(context.to_dict())

    assert parsed.workflow_id == "wf-42"
    assert parsed.assigned_tasks[0]["task_id"] == "task-2"
    assert parsed.conflict_signals[0]["file_path"] == "src/auth.py"

