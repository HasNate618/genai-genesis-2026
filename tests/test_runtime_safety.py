import subprocess
from pathlib import Path

import pytest

from backend.core.job_runtime import _apply_task_file_fallback
from backend.core.tool_runtime import ToolRuntimeError, WorkspaceToolRuntime
from backend.core.workdir_runtime import WorkdirRuntime


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )


def _init_repo(repo: Path, *, branch: str = "main") -> None:
    repo.mkdir()
    _run_git(repo, "init", "-b", branch)
    (repo / "sample.txt").write_text("base\n", encoding="utf-8")
    _run_git(repo, "add", "sample.txt")
    _run_git(
        repo,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "Initial commit",
    )


def _init_empty_repo(repo: Path, *, branch: str = "main") -> None:
    repo.mkdir()
    _run_git(repo, "init", "-b", branch)


def test_workdir_verification_workspace_contains_merged_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    runtime = WorkdirRuntime(repo_root=repo, workdir_root=tmp_path / ".workdirs")
    context = runtime.prepare_agent_workdir(job_id="job-1", agent_id="coder-1", base_branch="main")
    (context.path / "sample.txt").write_text("updated\n", encoding="utf-8")

    assert runtime.commit_all(context, message="Update sample file")

    verification = runtime.prepare_verification_workdir(
        job_id="job-1",
        base_branch="main",
        branches=[context.branch],
    )
    assert (verification.path / "sample.txt").read_text(encoding="utf-8") == "updated\n"

    runtime.cleanup_job("job-1")
    assert not verification.path.exists()


def test_workdir_falls_back_when_requested_base_branch_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo-master"
    _init_repo(repo, branch="master")

    runtime = WorkdirRuntime(repo_root=repo, workdir_root=tmp_path / ".workdirs")
    context = runtime.prepare_agent_workdir(
        job_id="job-2",
        agent_id="coder-1",
        base_branch="main",
    )

    head = _run_git(context.path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head == context.branch

    base_commit = _run_git(repo, "rev-parse", "master").stdout.strip()
    context_commit = _run_git(context.path, "rev-parse", "HEAD").stdout.strip()
    assert context_commit == base_commit

    runtime.cleanup_job("job-2")


def test_workdir_bootstraps_empty_repo_without_commits(tmp_path: Path) -> None:
    repo = tmp_path / "empty-repo"
    _init_empty_repo(repo, branch="master")

    runtime = WorkdirRuntime(repo_root=repo, workdir_root=tmp_path / ".workdirs")
    resolved = runtime.resolve_base_branch("main")
    assert resolved == "master"

    head_sha = _run_git(repo, "rev-parse", "--verify", "HEAD").stdout.strip()
    assert head_sha

    context = runtime.prepare_agent_workdir(
        job_id="job-3",
        agent_id="coder-1",
        base_branch="main",
    )
    context_sha = _run_git(context.path, "rev-parse", "HEAD").stdout.strip()
    assert context_sha == head_sha

    runtime.cleanup_job("job-3")


def test_tool_runtime_blocks_workspace_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = WorkspaceToolRuntime(root=workspace)

    assert runtime.run_command("ls .")["exit_code"] == 0

    with pytest.raises(ToolRuntimeError):
        runtime.run_command("cat /etc/passwd")
    with pytest.raises(ToolRuntimeError):
        runtime.run_command("ls ../")
    with pytest.raises(ToolRuntimeError):
        runtime.run_command("git -C /tmp status")
    with pytest.raises(ToolRuntimeError):
        runtime.run_command("python -c 'print(1)")


def test_task_file_fallback_scaffolds_concrete_targets_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = WorkspaceToolRuntime(root=workspace)

    created = _apply_task_file_fallback(
        runtime,
        ["workspace/task_1.txt", "snake_game/game.py", "README.md"],
    )
    assert "workspace/task_1.txt" not in created
    assert "snake_game/game.py" in created
    assert "README.md" in created
    assert (workspace / "snake_game/game.py").is_file()
    assert (workspace / "README.md").is_file()
