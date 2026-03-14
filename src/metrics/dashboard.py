"""
Metrics aggregation helpers for the Streamlit dashboard.

Fetches live data from the SPM API and formats it for display.
"""

from __future__ import annotations

from typing import Any

import httpx


class DashboardMetrics:
    """Thin client that pulls metrics from the running SPM API."""

    def __init__(self, api_base_url: str = "http://localhost:8000") -> None:
        self._base = api_base_url.rstrip("/")

    def _get(self, path: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self._base}{path}")
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)}

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def metrics(self) -> dict[str, Any]:
        return self._get("/metrics")

    def stats(self) -> dict[str, Any]:
        return self._get("/context/stats")
