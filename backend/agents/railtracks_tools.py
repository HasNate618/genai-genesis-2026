"""Railtracks function tools for repository interaction."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from backend.agents.workspace_guard import WorkspaceGuard, WorkspaceGuardError

_READ_ONLY_ROLES = {"planner", "task_coordinator", "conflict_analyst"}
_WRITE_ROLES = {"coding_agent", "merge_agent", "qa_agent"}
_IGNORED_PATH_PARTS = {".git", ".pytest_cache", "__pycache__", ".agent_workspaces", "venv"}


def build_tool_nodes(
    *,
    rt: Any,
    role: str,
    agent_id: str | None = None,
    guard: WorkspaceGuard | None = None,
) -> list[Any]:
    """Builds Railtracks tool nodes with role-scoped permissions."""
    workspace = guard or WorkspaceGuard()

    @rt.function_node
    def read_file(path: str) -> str:
        """Read a UTF-8 text file from repo root or workspace namespace.

        Args:
            path (str): Relative path. Use `workspace/...` to read from agent workspace.
        """

        resolved = workspace.resolve_read_path(path, agent_id=agent_id)
        if not resolved.is_file():
            raise WorkspaceGuardError(f"File not found: {path}")
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return workspace.truncate_output(content)

    @rt.function_node
    def glob_files(pattern: str) -> list[str]:
        """Find files under repository root using a glob pattern.

        Args:
            pattern (str): Glob pattern like `backend/**/*.py`.
        """

        if not pattern.strip():
            raise WorkspaceGuardError("Glob pattern is required.")
        matches: list[str] = []
        for path in workspace.repo_root.glob(pattern):
            if not path.is_file() or _is_ignored(path, workspace.repo_root):
                continue
            matches.append(_relative(path, workspace.repo_root))
            if len(matches) >= 300:
                break
        return matches

    @rt.function_node
    def grep_files(pattern: str, file_glob: str = "**/*") -> list[str]:
        """Search for regex pattern across text files.

        Args:
            pattern (str): Regex pattern to match.
            file_glob (str): Optional glob used to narrow files.
        """

        regex = re.compile(pattern)
        results: list[str] = []
        for path in workspace.repo_root.glob(file_glob):
            if not path.is_file() or _is_ignored(path, workspace.repo_root):
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append(f"{_relative(path, workspace.repo_root)}:{line_no}:{line[:220]}")
                    if len(results) >= 300:
                        return results
        return results

    @rt.function_node
    def write_file(path: str, content: str) -> str:
        """Write text to file under agent workspace by default or `repo/...`.

        Args:
            path (str): Relative file path. Prefix `repo/` for repository writes.
            content (str): Text content to write.
        """

        resolved = workspace.resolve_write_path(path, agent_id=agent_id)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {workspace.display_path(resolved)}"

    @rt.function_node
    def edit_file(path: str, target: str, replacement: str, replace_all: bool = False) -> str:
        """Replace text in file under workspace by default or `repo/...`.

        Args:
            path (str): Relative file path. Prefix `repo/` for repository edits.
            target (str): Exact text to replace.
            replacement (str): Replacement text.
            replace_all (bool): Replace all occurrences when true.
        """

        resolved = workspace.resolve_write_path(path, agent_id=agent_id)
        if not resolved.is_file():
            raise WorkspaceGuardError(f"File not found for edit: {path}")
        original = resolved.read_text(encoding="utf-8", errors="replace")
        if target not in original:
            raise WorkspaceGuardError("Target text not found in file.")
        updated = original.replace(target, replacement) if replace_all else original.replace(target, replacement, 1)
        resolved.write_text(updated, encoding="utf-8")
        return f"Edited {workspace.display_path(resolved)}"

    @rt.function_node
    def run_bash(command: str, cwd: str = "") -> dict[str, Any]:
        """Run an allowed command inside guarded workspace scope.

        Args:
            command (str): Command string, e.g. `python3 -m compileall backend`.
            cwd (str): Optional relative directory. Use `repo/...` for repo-root scope.
        """

        args = workspace.validate_command(command)
        run_cwd = workspace.resolve_command_cwd(cwd, agent_id=agent_id)
        result = subprocess.run(
            args,
            cwd=str(run_cwd),
            capture_output=True,
            text=True,
            timeout=workspace.command_timeout_seconds,
            check=False,
        )
        return {
            "exit_code": result.returncode,
            "cwd": workspace.display_path(run_cwd),
            "stdout": workspace.truncate_output(result.stdout),
            "stderr": workspace.truncate_output(result.stderr),
        }

    base_tools = [read_file, glob_files, grep_files]
    if role in _READ_ONLY_ROLES:
        return base_tools
    if role in _WRITE_ROLES:
        return [*base_tools, write_file, edit_file, run_bash]
    return base_tools


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def _is_ignored(path: Path, repo_root: Path) -> bool:
    relative = path.resolve().relative_to(repo_root.resolve())
    return any(part in _IGNORED_PATH_PARTS for part in relative.parts)
