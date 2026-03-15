"""GitHub API helpers for authenticated user-bound workflow operations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class GitHubRuntimeError(RuntimeError):
    """Raised when GitHub API operations fail."""


@dataclass(frozen=True)
class GitHubIdentity:
    """Authenticated GitHub user details."""

    login: str
    user_id: int
    html_url: str


class GitHubRuntime:
    """Thin GitHub REST wrapper scoped to a single user token and repository."""

    def __init__(self, *, access_token: str, repo_full_name: str | None = None) -> None:
        self._access_token = self._normalize_token(access_token)
        self.repo_full_name = self._normalize_repo(repo_full_name or "")
        self._api_base = "https://api.github.com"

    def whoami(self) -> GitHubIdentity:
        payload = self._request_json("GET", "/user")
        return GitHubIdentity(
            login=str(payload.get("login", "")),
            user_id=int(payload.get("id", 0) or 0),
            html_url=str(payload.get("html_url", "")),
        )

    def create_pull_request(
        self,
        *,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
        repo_full_name: str | None = None,
    ) -> dict[str, Any]:
        repo = self._resolve_repo_name(repo_full_name)
        return self._request_json(
            "POST",
            f"/repos/{repo}/pulls",
            {
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )

    def comment_on_pull_request(
        self, *, pull_number: int, body: str, repo_full_name: str | None = None
    ) -> dict[str, Any]:
        repo = self._resolve_repo_name(repo_full_name)
        return self._request_json(
            "POST",
            f"/repos/{repo}/issues/{pull_number}/comments",
            {"body": body},
        )

    def _resolve_repo_name(self, override: str | None) -> str:
        repo = self._normalize_repo(override or self.repo_full_name)
        if not repo:
            raise GitHubRuntimeError("repo_full_name is required.")
        return repo

    def _normalize_token(self, token: str) -> str:
        cleaned = token.strip()
        if cleaned.lower().startswith("bearer "):
            cleaned = cleaned.split(" ", 1)[1].strip()
        if not cleaned:
            raise GitHubRuntimeError("GitHub access token is required.")
        if "\n" in cleaned or "\r" in cleaned:
            raise GitHubRuntimeError("GitHub access token contains invalid characters.")
        return cleaned

    def _normalize_repo(self, repo: str) -> str:
        value = repo.strip()
        if not value:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise GitHubRuntimeError(f"Invalid GitHub repository name: {value}")
        return value

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentic-army-backend",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            url=f"{self._api_base}{path}",
            method=method,
            headers=headers,
            data=body,
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubRuntimeError(f"GitHub API error ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            raise GitHubRuntimeError(f"GitHub API request failed: {exc}") from exc

        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GitHubRuntimeError("GitHub API returned invalid JSON.") from exc
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
