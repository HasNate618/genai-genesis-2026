"""Isolated git workdir orchestration for coder agent execution."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class WorkdirRuntimeError(RuntimeError):
    """Raised when workdir or git operations fail."""


@dataclass(frozen=True)
class WorkdirContext:
    """Workspace metadata for a coder agent."""

    job_id: str
    agent_id: str
    branch: str
    path: Path


class WorkdirRuntime:
    """Creates and manages isolated git workdirs per job and coder agent."""

    def __init__(self, *, repo_root: Path | None = None, workdir_root: Path | None = None) -> None:
        self.repo_root = repo_root or self._detect_repo_root()
        self.workdir_root = workdir_root or self._default_workdir_root()
        self.workdir_root.mkdir(parents=True, exist_ok=True)
        self._contexts: dict[tuple[str, str], WorkdirContext] = {}
        self._contexts_by_job: dict[str, list[WorkdirContext]] = {}

    def prepare_agent_workdir(
        self, *, job_id: str, agent_id: str, base_branch: str = "main"
    ) -> WorkdirContext:
        key = (job_id, agent_id)
        existing = self._contexts.get(key)
        if existing is not None and existing.path.exists():
            try:
                self._run_git(["-C", str(existing.path), "checkout", existing.branch])
                self._run_git(["-C", str(existing.path), "reset", "--hard"])
                self._run_git(["-C", str(existing.path), "clean", "-fd"])
                return existing
            except WorkdirRuntimeError:
                self._run_git(["worktree", "remove", "--force", str(existing.path)], check=False)
                shutil.rmtree(existing.path, ignore_errors=True)

        branch = self._build_branch(job_id=job_id, agent_id=agent_id)
        path = self.workdir_root / job_id / agent_id
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            self._run_git(["worktree", "remove", "--force", str(path)], check=False)
            shutil.rmtree(path, ignore_errors=True)

        self._run_git(["worktree", "add", "-B", branch, str(path), base_branch])
        context = WorkdirContext(job_id=job_id, agent_id=agent_id, branch=branch, path=path)
        self._register_context(context)
        return context

    def prepare_verification_workdir(
        self, *, job_id: str, base_branch: str, branches: Iterable[str]
    ) -> WorkdirContext:
        context = self.prepare_agent_workdir(
            job_id=job_id,
            agent_id="verification",
            base_branch=base_branch,
        )
        self._run_git(["-C", str(context.path), "checkout", "-B", context.branch, base_branch])

        for branch in self._normalize_branches(branches):
            if branch in {base_branch, context.branch}:
                continue
            self._run_git(["rev-parse", "--verify", branch])
            self._run_git(["-C", str(context.path), "merge", "--no-ff", "--no-edit", branch])
        return context

    def commit_all(self, context: WorkdirContext, *, message: str) -> bool:
        self._run_git(["-C", str(context.path), "add", "-A"])
        status = self._run_git(["-C", str(context.path), "status", "--porcelain"]).stdout.strip()
        if not status:
            return False

        commit_message = self._sanitize_commit_message(message)
        self._run_git(
            [
                "-C",
                str(context.path),
                "-c",
                "user.name=AgenticArmy Bot",
                "-c",
                "user.email=agentic-army@local",
                "commit",
                "-m",
                commit_message,
            ]
        )
        return True

    def merge_branches(self, *, base_branch: str, branches: Iterable[str]) -> None:
        branches_to_merge = [
            branch for branch in self._normalize_branches(branches) if branch != base_branch
        ]
        if not branches_to_merge:
            return

        current_ref = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        self._run_git(["checkout", base_branch])
        try:
            for branch in branches_to_merge:
                self._run_git(["rev-parse", "--verify", branch])
                self._run_git(["merge", "--no-ff", "--no-edit", branch])
        finally:
            if current_ref and current_ref not in {base_branch, "HEAD"}:
                self._run_git(["checkout", current_ref], check=False)

    def cleanup_job(self, job_id: str) -> None:
        contexts = self._contexts_by_job.get(job_id, [])
        for context in contexts:
            self._run_git(["worktree", "remove", "--force", str(context.path)], check=False)
            shutil.rmtree(context.path, ignore_errors=True)
            self._contexts.pop((context.job_id, context.agent_id), None)
        self._contexts_by_job.pop(job_id, None)

    def detect_repo_full_name(self) -> str:
        raw = self._run_git(["config", "--get", "remote.origin.url"]).stdout.strip()
        if not raw:
            raise WorkdirRuntimeError("remote.origin.url is not configured.")

        https_match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", raw)
        if https_match:
            return https_match.group(1)
        raise WorkdirRuntimeError(f"Unable to parse GitHub repo from remote URL: {raw}")

    def _register_context(self, context: WorkdirContext) -> None:
        key = (context.job_id, context.agent_id)
        self._contexts[key] = context
        kept = [
            item
            for item in self._contexts_by_job.get(context.job_id, [])
            if item.agent_id != context.agent_id
        ]
        kept.append(context)
        self._contexts_by_job[context.job_id] = kept

    def _normalize_branches(self, branches: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for branch in branches:
            value = str(branch).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def _sanitize_commit_message(self, message: str) -> str:
        compact = " ".join(part.strip() for part in message.splitlines() if part.strip())
        return compact[:180] or "Agent update"

    def _run_git(
        self, args: list[str], *, check: bool = True, timeout: int = 60
    ) -> subprocess.CompletedProcess[str]:
        command = ["git", *args]
        result = subprocess.run(
            command,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            raise WorkdirRuntimeError(
                f"Git command failed ({result.returncode}): {' '.join(command)}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        return result

    def _detect_repo_root(self) -> Path:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            raise WorkdirRuntimeError(f"Not a git repository: {result.stderr}")
        return Path(result.stdout.strip())

    def _build_branch(self, *, job_id: str, agent_id: str) -> str:
        compact_job = re.sub(r"[^a-zA-Z0-9]+", "-", job_id)[:24]
        compact_agent = re.sub(r"[^a-zA-Z0-9]+", "-", agent_id)[:24]
        return f"agentic/{compact_job}/{compact_agent}"

    def _default_workdir_root(self) -> Path:
        repo_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", self.repo_root.name).strip("-") or "repo"
        return Path(tempfile.gettempdir()) / "agenticarmy-workdirs" / repo_slug
