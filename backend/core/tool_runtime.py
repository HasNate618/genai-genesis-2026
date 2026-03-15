"""Tooling primitives exposed to coder/qa agents."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from backend.core.github_runtime import GitHubRuntime


class ToolRuntimeError(RuntimeError):
    """Raised when a tool action fails or violates safety constraints."""


ALLOWED_COMMANDS = {
    "python",
    "python3",
    "pytest",
    "npm",
    "node",
    "pip",
    "pip3",
    "uv",
    "git",
    "ls",
    "cat",
    "rg",
    "find",
    "head",
    "tail",
    "sed",
    "awk",
}
BLOCKED_GIT_FLAGS = {"-C", "--git-dir", "--work-tree"}


class WorkspaceToolRuntime:
    """Safe, path-scoped tool executor for a single workdir."""

    def __init__(self, *, root: Path, github_runtime: GitHubRuntime | None = None) -> None:
        self.root = root.resolve()
        self.github_runtime = github_runtime

    def list_files(self, rel_path: str = ".") -> list[str]:
        target = self._resolve(rel_path)
        if target.is_file():
            return [str(target.relative_to(self.root))]
        if not target.exists():
            raise ToolRuntimeError(f"Path does not exist: {rel_path}")
        return sorted(str(p.relative_to(self.root)) for p in target.rglob("*") if p.is_file())

    def read_file(self, rel_path: str) -> str:
        path = self._resolve(rel_path)
        if not path.is_file():
            raise ToolRuntimeError(f"File not found: {rel_path}")
        return path.read_text(encoding="utf-8")

    def write_file(self, rel_path: str, content: str) -> str:
        path = self._resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root))

    def run_command(self, command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise ToolRuntimeError(f"Invalid command syntax: {exc}") from exc
        if not parts:
            raise ToolRuntimeError("Command cannot be empty.")
        if parts[0] not in ALLOWED_COMMANDS:
            raise ToolRuntimeError(f"Command not allowed: {parts[0]}")
        self._validate_command(parts)

        try:
            result = subprocess.run(
                parts,
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolRuntimeError(
                f"Command timed out after {timeout_seconds}s: {parts[0]}"
            ) from exc
        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def git_status(self) -> str:
        result = self.run_command("git status --short")
        return str(result["stdout"])

    def git_diff(self) -> str:
        result = self.run_command("git diff")
        return str(result["stdout"])

    def github_whoami(self) -> dict[str, Any]:
        if self.github_runtime is None:
            raise ToolRuntimeError("GitHub runtime is not configured.")
        identity = self.github_runtime.whoami()
        return {"login": identity.login, "id": identity.user_id, "html_url": identity.html_url}

    def github_create_pull_request(
        self, *, title: str, head: str, base: str, body: str = ""
    ) -> dict[str, Any]:
        if self.github_runtime is None:
            raise ToolRuntimeError("GitHub runtime is not configured.")
        return self.github_runtime.create_pull_request(
            title=title, head=head, base=base, body=body
        )

    def build_railtracks_tool_nodes(self, rt: Any) -> list[Any]:
        """Wraps bound methods as Railtracks function_node tools."""

        @rt.function_node
        def list_files(rel_path: str = ".") -> list[str]:
            """List files under a relative path in the assigned workspace."""

            return self.list_files(rel_path)

        @rt.function_node
        def read_file(path: str) -> str:
            """Read a UTF-8 text file from the assigned workspace."""

            return self.read_file(path)

        @rt.function_node
        def write_file(path: str, content: str) -> str:
            """Write UTF-8 text content to a workspace file."""

            return self.write_file(path, content)

        @rt.function_node
        def run_command(command: str, timeout_seconds: int = 120) -> dict[str, Any]:
            """Run an allowlisted shell command in the assigned workspace."""

            return self.run_command(command, timeout_seconds)

        @rt.function_node
        def git_status() -> str:
            """Return git status for current workspace."""

            return self.git_status()

        @rt.function_node
        def git_diff() -> str:
            """Return git diff for current workspace."""

            return self.git_diff()

        nodes = [list_files, read_file, write_file, run_command, git_status, git_diff]
        if self.github_runtime is not None:
            @rt.function_node
            def github_whoami() -> dict[str, Any]:
                """Return authenticated GitHub identity."""

                return self.github_whoami()

            @rt.function_node
            def github_create_pull_request(
                title: str, head: str, base: str, body: str = ""
            ) -> dict[str, Any]:
                """Create a GitHub pull request for the configured repository."""

                return self.github_create_pull_request(
                    title=title, head=head, base=base, body=body
                )

            nodes.extend([github_whoami, github_create_pull_request])

        return nodes

    def _resolve(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        if self.root != target and self.root not in target.parents:
            raise ToolRuntimeError(f"Path escapes workspace root: {rel_path}")
        return target

    def _validate_command(self, parts: list[str]) -> None:
        cmd = parts[0]

        # Disallow inline code execution for general-purpose interpreters so that
        # path/argument validation cannot be bypassed via strings like
        # `python -c 'open("/etc/passwd").read()'` or `node -e '...'`.
        if cmd in ("python", "python3"):
            for arg in parts[1:]:
                if arg == "-c" or arg.startswith("-c"):
                    raise ToolRuntimeError(
                        "Inline code execution with 'python -c' is not allowed in workspace mode."
                    )
        elif cmd == "node":
            for arg in parts[1:]:
                if arg == "-e" or arg.startswith("-e"):
                    raise ToolRuntimeError(
                        "Inline code execution with 'node -e' is not allowed in workspace mode."
                    )

        if cmd == "git":
            for arg in parts[1:]:
                if arg in BLOCKED_GIT_FLAGS:
                    raise ToolRuntimeError(f"Git flag is not allowed in workspace mode: {arg}")
                if any(arg.startswith(f"{flag}=") for flag in BLOCKED_GIT_FLAGS):
                    raise ToolRuntimeError(f"Git flag is not allowed in workspace mode: {arg}")

        for arg in parts[1:]:
            if arg.startswith("-"):
                continue
            if arg.startswith("/") or arg.startswith("~"):
                raise ToolRuntimeError("Absolute paths are not allowed in workspace commands.")
            if ".." in Path(arg).parts:
                raise ToolRuntimeError("Path traversal is not allowed in workspace commands.")
