"""
Metrics collector: tracks latency, compression, conflict prevention stats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * p / 100
    lo = int(idx)
    hi = lo + 1
    if hi >= len(sorted_data):
        return sorted_data[-1]
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


class MetricsCollector:
    def __init__(self) -> None:
        self.operation_latencies: dict[str, list[float]] = {}
        self.compression_ratios: list[float] = []
        self.grounding_rates: list[float] = []
        self.conflict_prevention_count: int = 0
        self.conflict_allowed_count: int = 0
        self.total_operations: int = 0

    def record_operation(self, name: str, duration_ms: float) -> None:
        if name not in self.operation_latencies:
            self.operation_latencies[name] = []
        self.operation_latencies[name].append(duration_ms)
        self.total_operations += 1

    def record_compaction(self, result: Any) -> None:
        """Accept a CompactionResult dataclass."""
        if result.compression_ratio > 0:
            self.compression_ratios.append(result.compression_ratio)
        logger.info(
            "metrics.compaction",
            ratio=result.compression_ratio,
            records_before=result.records_before,
            records_after=result.records_after,
        )

    def record_conflict(self, prevented: bool) -> None:
        if prevented:
            self.conflict_prevention_count += 1
        else:
            self.conflict_allowed_count += 1

    def record_grounding(self, grounded: bool) -> None:
        self.grounding_rates.append(1.0 if grounded else 0.0)

    def get_summary(self) -> dict[str, Any]:
        latency_stats: dict[str, Any] = {}
        for op, latencies in self.operation_latencies.items():
            latency_stats[op] = {
                "count": len(latencies),
                "p50": round(_percentile(latencies, 50), 2),
                "p95": round(_percentile(latencies, 95), 2),
                "p99": round(_percentile(latencies, 99), 2),
                "mean": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            }

        avg_compression = (
            sum(self.compression_ratios) / len(self.compression_ratios)
            if self.compression_ratios
            else 0.0
        )
        avg_grounding = (
            sum(self.grounding_rates) / len(self.grounding_rates)
            if self.grounding_rates
            else 0.0
        )
        total_conflict = self.conflict_prevention_count + self.conflict_allowed_count
        prevention_rate = (
            self.conflict_prevention_count / total_conflict if total_conflict else 0.0
        )

        return {
            "total_operations": self.total_operations,
            "latency_by_operation": latency_stats,
            "avg_compression_ratio": round(avg_compression, 4),
            "avg_grounding_rate": round(avg_grounding, 4),
            "conflict_prevention_count": self.conflict_prevention_count,
            "conflict_allowed_count": self.conflict_allowed_count,
            "conflict_prevention_rate": round(prevention_rate, 4),
        }

    def get_latency_histogram(self) -> dict[str, Any]:
        """Return histogram data suitable for plotting."""
        all_latencies: list[float] = []
        for latencies in self.operation_latencies.values():
            all_latencies.extend(latencies)

        if not all_latencies:
            return {"buckets": [], "counts": []}

        max_val = max(all_latencies)
        bucket_size = max(1.0, max_val / 10)
        buckets: list[float] = [i * bucket_size for i in range(11)]
        counts: list[int] = [0] * 10

        for val in all_latencies:
            bucket_idx = min(9, int(val / bucket_size))
            counts[bucket_idx] += 1

        return {
            "buckets": [f"{b:.0f}-{b + bucket_size:.0f}ms" for b in buckets[:10]],
            "counts": counts,
        }
