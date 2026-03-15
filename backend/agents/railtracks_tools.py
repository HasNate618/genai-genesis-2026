"""Railtracks function tools for repository interaction."""

from __future__ import annotations

import re
import subprocess
import threading
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
        if ".." in pattern:
            raise WorkspaceGuardError("Glob pattern must not contain '..' path traversal.")
        matches: list[str] = []
        for path in workspace.repo_root.glob(pattern):
            resolved = path.resolve()
            if not resolved.is_relative_to(workspace.repo_root):
                continue
            if not resolved.is_file() or _is_ignored(resolved, workspace.repo_root):
                continue
            matches.append(_relative(resolved, workspace.repo_root))
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

        if ".." in file_glob:
            raise WorkspaceGuardError("File glob must not contain '..' path traversal.")
        regex = re.compile(pattern)
        results: list[str] = []
        for path in workspace.repo_root.glob(file_glob):
            resolved = path.resolve()
            if not resolved.is_relative_to(workspace.repo_root):
                continue
            if not resolved.is_file() or _is_ignored(resolved, workspace.repo_root):
                continue
            if resolved.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}:
                continue
            text = resolved.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append(f"{_relative(resolved, workspace.repo_root)}:{line_no}:{line[:220]}")
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

        # Determine the maximum amount of output to buffer per stream. Fall back to a
        # reasonable default if the workspace does not expose a max_output_bytes setting.
        max_output_chars = getattr(workspace, "max_output_bytes", 1_000_000)

        process = subprocess.Popen(
            args,
            cwd=str(run_cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_len = 0
        stderr_len = 0

        def _reader(pipe, chunks: list[str], length_ref: list[int]) -> None:
            # length_ref is a single-element list used to keep track of total length
            try:
                for chunk in iter(lambda: pipe.read(4096), ""):
                    if length_ref[0] >= max_output_chars:
                        break
                    remaining = max_output_chars - length_ref[0]
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    chunks.append(chunk)
                    length_ref[0] += len(chunk)
                    if length_ref[0] >= max_output_chars:
                        break
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        stdout_len_ref = [stdout_len]
        stderr_len_ref = [stderr_len]

        stdout_thread = threading.Thread(
            target=_reader, args=(process.stdout, stdout_chunks, stdout_len_ref), daemon=True
        )
        stderr_thread = threading.Thread(
            target=_reader, args=(process.stderr, stderr_chunks, stderr_len_ref), daemon=True
        )

        stdout_thread.start()
        stderr_thread.start()

        try:
            # Preserve timeout behavior similar to subprocess.run(..., timeout=...).
            process.wait(timeout=workspace.command_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            # Ensure threads finish reading whatever is left in the pipes.
            stdout_thread.join()
            stderr_thread.join()
            # Re-raise to match the original behavior where subprocess.run would raise.
            raise

        # Ensure all output has been read.
        stdout_thread.join()
        stderr_thread.join()

        stdout_str = "".join(stdout_chunks)
        stderr_str = "".join(stderr_chunks)

        return {
            "exit_code": process.returncode,
            "cwd": workspace.display_path(run_cwd),
            "stdout": workspace.truncate_output(stdout_str),
            "stderr": workspace.truncate_output(stderr_str),
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
