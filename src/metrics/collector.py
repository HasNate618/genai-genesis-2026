"""
Metrics collector — records latency, compaction, conflict, and retrieval stats.

Wraps every significant operation to build the data for the Streamlit
dashboard and the demo narrative.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any


class MetricsCollector:
    """Thread-safe (append-only) in-process metrics store."""

    _MAX_LATENCY_SAMPLES = 500

    def __init__(self) -> None:
        self._request_latencies: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._MAX_LATENCY_SAMPLES)
        )
        self._retrieval_latencies: deque = deque(maxlen=self._MAX_LATENCY_SAMPLES)
        self._retrieval_doc_counts: deque = deque(maxlen=self._MAX_LATENCY_SAMPLES)

        self._conflict_counts: dict[str, int] = defaultdict(int)  # action → count
        self._compaction_ratios: list[float] = []
        self._compaction_docs_deleted: list[int] = []
        self._start_time = time.time()

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_request(self, path: str, latency_ms: float) -> None:
        self._request_latencies[path].append(latency_ms)

    def record_retrieval(self, latency_ms: float, doc_count: int) -> None:
        self._retrieval_latencies.append(latency_ms)
        self._retrieval_doc_counts.append(doc_count)

    def record_conflict_check(self, action: str) -> None:
        self._conflict_counts[action] += 1

    def record_compaction(self, compression_ratio: float, docs_deleted: int) -> None:
        self._compaction_ratios.append(compression_ratio)
        self._compaction_docs_deleted.append(docs_deleted)

    # ── Aggregation ───────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        def _avg(seq) -> float:
            lst = list(seq)
            return round(sum(lst) / len(lst), 2) if lst else 0.0

        def _p95(seq) -> float:
            lst = sorted(seq)
            if not lst:
                return 0.0
            idx = max(0, int(len(lst) * 0.95) - 1)
            return round(lst[idx], 2)

        retrieval_lat = list(self._retrieval_latencies)

        return {
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "retrieval": {
                "avg_latency_ms": _avg(retrieval_lat),
                "p95_latency_ms": _p95(retrieval_lat),
                "total_queries": len(retrieval_lat),
                "avg_docs_returned": _avg(self._retrieval_doc_counts),
            },
            "conflict": {
                "proceed_count": self._conflict_counts.get("proceed", 0),
                "warn_count": self._conflict_counts.get("warn", 0),
                "block_count": self._conflict_counts.get("block", 0),
                "total": sum(self._conflict_counts.values()),
            },
            "compaction": {
                "runs": len(self._compaction_ratios),
                "avg_compression_ratio": _avg(self._compaction_ratios),
                "total_docs_deleted": sum(self._compaction_docs_deleted),
            },
            "request_latency_by_path": {
                path: {"avg_ms": _avg(lats), "p95_ms": _p95(lats)}
                for path, lats in self._request_latencies.items()
            },
        }

    def latency_histogram(self, bins: int = 10) -> dict[str, Any]:
        """Return a simple histogram of retrieval latencies for the dashboard."""
        lats = sorted(self._retrieval_latencies)
        if not lats:
            return {"bins": [], "counts": []}
        min_l, max_l = lats[0], lats[-1]
        if min_l == max_l:
            return {"bins": [min_l], "counts": [len(lats)]}
        step = (max_l - min_l) / bins
        boundaries = [min_l + step * i for i in range(bins + 1)]
        counts = [0] * bins
        for l in lats:
            idx = min(int((l - min_l) / step), bins - 1)
            counts[idx] += 1
        return {
            "bins": [round(b, 1) for b in boundaries[:-1]],
            "counts": counts,
        }
