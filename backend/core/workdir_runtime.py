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
        resolved_base_branch = self.resolve_base_branch(base_branch)
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

        self._run_git(["worktree", "add", "-B", branch, str(path), resolved_base_branch])
        context = WorkdirContext(job_id=job_id, agent_id=agent_id, branch=branch, path=path)
        self._register_context(context)
        return context

    def prepare_verification_workdir(
        self, *, job_id: str, base_branch: str, branches: Iterable[str]
    ) -> WorkdirContext:
        resolved_base_branch = self.resolve_base_branch(base_branch)
        context = self.prepare_agent_workdir(
            job_id=job_id,
            agent_id="verification",
            base_branch=resolved_base_branch,
        )
        self._run_git(["-C", str(context.path), "checkout", "-B", context.branch, resolved_base_branch])

        for branch in self._normalize_branches(branches):
            if branch in {resolved_base_branch, context.branch}:
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

    def merge_branches(self, *, base_branch: str, branches: Iterable[str]) -> bool:
        """Merge *branches* into *base_branch* using a disposable worktree.

        After updating the branch ref the method attempts to sync the main
        working tree so that new files are immediately visible in the editor.
        Returns True when the working tree was synced, False when it was left
        untouched (e.g. it was dirty or checked out to a different branch).
        """
        resolved_base_branch = self.resolve_base_branch(base_branch)
        branches_to_merge = [
            branch for branch in self._normalize_branches(branches) if branch != resolved_base_branch
        ]
        if not branches_to_merge:
            return False

        merge_dir = self.workdir_root / "_merge-finalize"
        merge_branch = "_agentic-merge-temp"

        if merge_dir.exists():
            self._run_git(["worktree", "remove", "--force", str(merge_dir)], check=False)
            shutil.rmtree(merge_dir, ignore_errors=True)
        merge_dir.parent.mkdir(parents=True, exist_ok=True)

        # Snapshot the working tree state BEFORE advancing the branch ref.
        # We check for user-made uncommitted changes now, so that the subsequent
        # `git reset --hard HEAD` (after update-ref) doesn't clobber anything.
        workdir_eligible = self._workdir_eligible_for_sync(resolved_base_branch)

        self._run_git(["worktree", "add", "-B", merge_branch, str(merge_dir), resolved_base_branch])
        try:
            for branch in branches_to_merge:
                self._run_git(["rev-parse", "--verify", branch])
                self._run_git(["-C", str(merge_dir), "merge", "--no-ff", "--no-edit", branch])

            merged_sha = self._run_git(
                ["-C", str(merge_dir), "rev-parse", "HEAD"]
            ).stdout.strip()
            self._run_git(["update-ref", f"refs/heads/{resolved_base_branch}", merged_sha])
        finally:
            self._run_git(["worktree", "remove", "--force", str(merge_dir)], check=False)
            shutil.rmtree(merge_dir, ignore_errors=True)
            self._run_git(["branch", "-D", merge_branch], check=False)

        if workdir_eligible:
            # Branch ref now points to merged_sha; reset the working tree to match.
            self._run_git(["reset", "--hard", "HEAD"], check=False)
            return True
        return False

    def _workdir_eligible_for_sync(self, branch: str) -> bool:
        """Return True when the main working tree can be safely fast-forwarded.

        Conditions: the working tree is checked out on *branch* and has no
        uncommitted changes (staged or unstaged).  This must be called BEFORE
        update-ref so that the status comparison is against the current HEAD,
        not the incoming merged HEAD.
        """
        current = self._run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"], check=False
        ).stdout.strip()
        if current != branch:
            return False
        dirty = self._run_git(["status", "--porcelain"], check=False).stdout.strip()
        return not dirty

    def head_commit(self, ref: str = "HEAD") -> str:
        return self._run_git(["rev-parse", ref]).stdout.strip()

    def changed_files_in_ref(self, ref: str = "HEAD") -> list[str]:
        output = self._run_git(["show", "--pretty=format:", "--name-only", ref]).stdout
        return [line.strip() for line in output.splitlines() if line.strip()]

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

    def resolve_base_branch(self, preferred_branch: str = "main") -> str:
        candidate = str(preferred_branch).strip()
        if candidate and self._local_branch_exists(candidate):
            return candidate

        if not self._has_commits():
            current_head = self._current_head_branch()
            bootstrap_branch = candidate
            if candidate == "main" and current_head and current_head != "HEAD":
                bootstrap_branch = current_head
            if not bootstrap_branch:
                bootstrap_branch = current_head or "main"
            return self._bootstrap_initial_branch(bootstrap_branch)

        current = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], check=False).stdout.strip()
        if current and current != "HEAD" and self._local_branch_exists(current):
            return current

        refs_output = self._run_git(
            ["for-each-ref", "--format=%(refname:short)", "refs/heads"],
            check=False,
        ).stdout
        for line in refs_output.splitlines():
            branch = line.strip()
            if branch:
                return branch

        raise WorkdirRuntimeError(
            "No local branch available for worktree base. "
            "Create an initial commit and branch in the target repository."
        )

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

    def _local_branch_exists(self, branch: str) -> bool:
        result = self._run_git(["show-ref", "--verify", f"refs/heads/{branch}"], check=False)
        return result.returncode == 0

    def _has_commits(self) -> bool:
        result = self._run_git(["rev-parse", "--verify", "HEAD"], check=False)
        return result.returncode == 0

    def _current_head_branch(self) -> str:
        result = self._run_git(["symbolic-ref", "--short", "HEAD"], check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def _bootstrap_initial_branch(self, branch: str) -> str:
        branch_name = str(branch).strip() or "main"
        checkout = self._run_git(["checkout", "-B", branch_name], check=False)
        if checkout.returncode != 0:
            raise WorkdirRuntimeError(
                "Unable to create initial branch for empty repository: "
                f"{branch_name}\nstdout: {checkout.stdout}\nstderr: {checkout.stderr}"
            )

        commit = self._run_git(
            [
                "-c",
                "user.name=AgenticArmy Bot",
                "-c",
                "user.email=agentic-army@local",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                "Initialize repository for AgenticArmy",
            ],
            check=False,
        )
        if commit.returncode != 0:
            raise WorkdirRuntimeError(
                "Unable to create initial commit for empty repository.\n"
                f"stdout: {commit.stdout}\nstderr: {commit.stderr}"
            )
        return branch_name

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
