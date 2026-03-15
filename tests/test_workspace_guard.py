import pytest

from backend.agents.workspace_guard import WorkspaceGuard, WorkspaceGuardError


def test_write_path_defaults_to_agent_workspace(tmp_path) -> None:
    guard = WorkspaceGuard(repo_root=tmp_path)
    resolved = guard.resolve_write_path("notes/output.txt", agent_id="coder-1")

    assert resolved == (tmp_path / ".agent_workspaces" / "coder-1" / "notes" / "output.txt").resolve()


def test_write_path_repo_prefix_targets_repo_root(tmp_path) -> None:
    guard = WorkspaceGuard(repo_root=tmp_path)
    resolved = guard.resolve_write_path("repo/backend/api/routes.py", agent_id="coder-2")

    assert resolved == (tmp_path / "backend" / "api" / "routes.py").resolve()


def test_path_escape_is_rejected(tmp_path) -> None:
    guard = WorkspaceGuard(repo_root=tmp_path)

    with pytest.raises(WorkspaceGuardError):
        guard.resolve_write_path("../../etc/passwd", agent_id="coder-1")


def test_validate_command_allows_safe_binary_and_blocks_privileged(tmp_path) -> None:
    guard = WorkspaceGuard(repo_root=tmp_path)

    args = guard.validate_command("python3 -m compileall backend")
    assert args[0] == "python3"

    with pytest.raises(WorkspaceGuardError):
        guard.validate_command("sudo ls")
