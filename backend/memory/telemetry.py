"""In-memory telemetry for Moorcheh integration diagnostics."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class MemoryTelemetry:
    """Tracks operational counters and latencies for memory operations."""

    write_calls: int = 0
    write_vectors: int = 0
    search_calls: int = 0
    search_results: int = 0
    provision_calls: int = 0
    health_calls: int = 0
    errors: int = 0
    last_error: str | None = None
    recent_write_ms: list[float] = field(default_factory=list)
    recent_search_ms: list[float] = field(default_factory=list)

    def record_write(self, *, count: int, elapsed_seconds: float) -> None:
        self.write_calls += 1
        self.write_vectors += count
        self.recent_write_ms.append(elapsed_seconds * 1000.0)
        self.recent_write_ms = self.recent_write_ms[-50:]

    def record_search(self, *, count: int, elapsed_seconds: float) -> None:
        self.search_calls += 1
        self.search_results += count
        self.recent_search_ms.append(elapsed_seconds * 1000.0)
        self.recent_search_ms = self.recent_search_ms[-50:]

    def record_provision(self) -> None:
        self.provision_calls += 1

    def record_health(self) -> None:
        self.health_calls += 1

    def record_error(self, message: str) -> None:
        self.errors += 1
        self.last_error = message

    def snapshot(self) -> dict[str, float | int | str | None]:
        return {
            "write_calls": self.write_calls,
            "write_vectors": self.write_vectors,
            "search_calls": self.search_calls,
            "search_results": self.search_results,
            "provision_calls": self.provision_calls,
            "health_calls": self.health_calls,
            "errors": self.errors,
            "last_error": self.last_error,
            "avg_write_ms": _average(self.recent_write_ms),
            "avg_search_ms": _average(self.recent_search_ms),
        }


@contextmanager
def elapsed_timer() -> Iterator[callable[[], float]]:
    start = time.perf_counter()

    def elapsed() -> float:
        return time.perf_counter() - start

    yield elapsed


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)

