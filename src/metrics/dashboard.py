"""
Dashboard metrics aggregator for Streamlit UI.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.memory.store import MoorchehStore
from src.memory.index import SQLiteIndex
from src.memory.schemas import RecordType, RecordStatus
from src.metrics.collector import MetricsCollector

logger = structlog.get_logger(__name__)


class DashboardMetrics:
    def __init__(
        self,
        store: MoorchehStore,
        index: SQLiteIndex,
        metrics: MetricsCollector,
    ) -> None:
        self._store = store
        self._index = index
        self._metrics = metrics

    def get_active_claims(self, project_id: str) -> list[dict[str, Any]]:
        records = self._store.list_records(
            filters={"project_id": project_id, "record_type": RecordType.task_claim.value}
        )
        active = [
            r
            for r in records
            if r.status not in (RecordStatus.done.value, RecordStatus.superseded.value)
        ]
        return [
            {
                "record_id": r.id,
                "agent_id": r.agent_id,
                "task": r.payload.get("task_description", r.text[:80]),
                "status": r.status,
                "files": r.payload.get("file_paths", []),
                "timestamp": r.timestamp,
                "importance": r.importance,
            }
            for r in sorted(active, key=lambda x: x.timestamp, reverse=True)
        ]

    def get_conflict_alerts(self, project_id: str) -> list[dict[str, Any]]:
        records = self._store.list_records(
            filters={"project_id": project_id, "record_type": RecordType.conflict_alert.value}
        )
        alerts = []
        for r in sorted(records, key=lambda x: x.timestamp, reverse=True)[:20]:
            alerts.append(
                {
                    "record_id": r.id,
                    "timestamp": r.timestamp,
                    "risk_score": r.payload.get("risk_score", 0.0),
                    "recommendation": r.payload.get("recommendation", "proceed"),
                    "channels": r.payload.get("channels", {}),
                    "conflicting_ids": r.payload.get("conflicting_record_ids", []),
                    "text": r.text[:200],
                }
            )
        return alerts

    def get_memory_stats(self, project_id: str) -> dict[str, Any]:
        records = self._store.list_records(filters={"project_id": project_id})
        total_chars = sum(len(r.text) for r in records)
        summaries = [r for r in records if r.record_type == RecordType.summary.value]
        total_chars_before = sum(
            r.payload.get("chars_before", 0) for r in summaries
        )
        total_chars_after = sum(len(r.text) for r in summaries)
        ratio = total_chars_before / max(1, total_chars_after) if summaries else 1.0

        index_stats = self._index.get_stats()
        return {
            "total_records": len(records),
            "total_chars": total_chars,
            "summary_count": len(summaries),
            "compression_ratio": round(ratio, 2),
            **index_stats,
        }

    def get_latency_histogram(self) -> dict[str, Any]:
        return self._metrics.get_latency_histogram()

    def get_summary_stats(self) -> dict[str, Any]:
        return self._metrics.get_summary()
