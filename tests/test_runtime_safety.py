import subprocess
from pathlib import Path

import pytest

from backend.core.tool_runtime import ToolRuntimeError, WorkspaceToolRuntime
from backend.core.workdir_runtime import WorkdirRuntime


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
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
