"""Workspace safety primitives for Railtracks tool execution."""

from __future__ import annotations

import shlex
from pathlib import Path

DEFAULT_WORKSPACES_DIR = ".agent_workspaces"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 45
DEFAULT_MAX_OUTPUT_BYTES = 200_000

_ALLOWED_BINARIES = {
    "python",
    "python3",
    "pytest",
    "pip",
    "pip3",
    "uv",
    "npm",
    "npx",
    "node",
    "go",
    "git",
    "ls",
    "cat",
    "rg",
    "grep",
    "sed",
    "awk",
    "make",
    "bash",
    "sh",
}
_BLOCKED_BINARIES = {"sudo", "kill", "pkill", "killall", "chmod", "chown"}


class WorkspaceGuardError(ValueError):
    """Raised when a workspace/tool request violates guard constraints."""


class WorkspaceGuard:
    """Validates paths, command execution scope, and output limits."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        workspaces_dir: str = DEFAULT_WORKSPACES_DIR,
        command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        default_root = Path(__file__).resolve().parents[2]
        self.repo_root = (repo_root or default_root).resolve()
        self.workspaces_root = (self.repo_root / workspaces_dir).resolve()
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.command_timeout_seconds = max(1, command_timeout_seconds)
        self.max_output_bytes = max(1, max_output_bytes)

    def agent_workspace(self, agent_id: str | None) -> Path:
        """Returns the per-agent workspace path, creating it if needed."""
        safe_agent_id = self._sanitize_agent_id(agent_id)
        workspace = (self.workspaces_root / safe_agent_id).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def resolve_read_path(self, path: str, *, agent_id: str | None = None) -> Path:
        """Resolves read targets under repo root or agent workspace namespace."""
        raw = (path or "").strip()
        if not raw:
            raise WorkspaceGuardError("Path is required.")
        if raw.startswith("workspace/"):
            return self._resolve_under(self.agent_workspace(agent_id), raw[len("workspace/") :])
        return self._resolve_under(self.repo_root, raw)

    def resolve_write_path(self, path: str, *, agent_id: str | None = None) -> Path:
        """Resolves write/edit targets under workspace by default or `repo/` prefix."""
        raw = (path or "").strip()
        if not raw:
            raise WorkspaceGuardError("Path is required.")
        if raw.startswith("repo/"):
            return self._resolve_under(self.repo_root, raw[len("repo/") :])
        return self._resolve_under(self.agent_workspace(agent_id), raw)

    def resolve_command_cwd(self, cwd: str | None, *, agent_id: str | None = None) -> Path:
        """Resolves command working directory with repo/workspace safety boundaries."""
        raw = (cwd or "").strip()
        if not raw:
            return self.agent_workspace(agent_id)
        if raw.startswith("repo/"):
            return self._resolve_under(self.repo_root, raw[len("repo/") :])
        return self._resolve_under(self.agent_workspace(agent_id), raw)

    def validate_command(self, command: str) -> list[str]:
        """Parses and validates command against binary policy."""
        raw = (command or "").strip()
        if not raw:
            raise WorkspaceGuardError("Command is required.")
        try:
            args = shlex.split(raw)
        except ValueError as exc:
            raise WorkspaceGuardError(f"Invalid command syntax: {exc}") from exc
        if not args:
            raise WorkspaceGuardError("Command is required.")

        binary = Path(args[0]).name.lower()
        if binary in _BLOCKED_BINARIES:
            raise WorkspaceGuardError(f"Command '{binary}' is blocked.")
        if binary not in _ALLOWED_BINARIES:
            raise WorkspaceGuardError(
                f"Command '{binary}' is not in the allowed binary list."
            )
        return args

    def display_path(self, path: Path) -> str:
        """Renders path relative to repository root when possible."""
        resolved = path.resolve()
        try:
            return str(resolved.relative_to(self.repo_root))
        except ValueError:
            return str(resolved)

    def truncate_output(self, text: str) -> str:
        """Truncates command output to configured byte size."""
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= self.max_output_bytes:
            return text
        truncated = encoded[: self.max_output_bytes].decode("utf-8", errors="ignore")
        return f"{truncated}\n...[truncated]"

    def _resolve_under(self, base: Path, raw_path: str) -> Path:
        raw = (raw_path or "").strip()
        if not raw:
            raise WorkspaceGuardError("Path is required.")
        if raw == ".":
            target = base.resolve()
        else:
            candidate = Path(raw)
            target = (
                candidate.expanduser().resolve()
                if candidate.is_absolute()
                else (base / candidate).resolve()
            )
        if not target.is_relative_to(base):
            raise WorkspaceGuardError(
                f"Path '{raw_path}' escapes allowed workspace '{base}'."
            )
        return target

    def _sanitize_agent_id(self, agent_id: str | None) -> str:
        raw = (agent_id or "shared").strip()
        allowed_chars = []
        for char in raw:
            if char.isalnum() or char in {"-", "_"}:
                allowed_chars.append(char)
        value = "".join(allowed_chars)
        return value or "shared"
