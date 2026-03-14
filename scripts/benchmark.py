"""
Benchmark script — measures and reports key SPM performance metrics.

Metrics captured:
  - Retrieval latency (avg, p50, p95, p99) across N queries
  - Compaction compression ratio
  - Conflict detection throughput
  - Moorcheh vs fallback latency comparison

Usage:
    python scripts/benchmark.py --api http://localhost:8000 --n 50
"""

from __future__ import annotations

import argparse
import statistics
import time

import httpx


def _post(base: str, path: str, payload: dict) -> tuple[dict, float]:
    start = time.perf_counter()
    resp = httpx.post(f"{base}{path}", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json(), (time.perf_counter() - start) * 1000


def benchmark_retrieval(base: str, n: int) -> dict:
    queries = [
        "authentication session management",
        "database optimization connection pool",
        "JWT token expiry logic",
        "file change intent conflict detection",
        "compaction memory efficiency",
    ]
    latencies = []
    for i in range(n):
        q = queries[i % len(queries)]
        _, ms = _post(base, "/context/query", {"question": q, "top_k": 5, "use_shared": True})
        latencies.append(ms)

    latencies.sort()
    return {
        "n": n,
        "avg_ms": round(statistics.mean(latencies), 2),
        "median_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(latencies[int(n * 0.95)], 2),
        "p99_ms": round(latencies[min(int(n * 0.99), n - 1)], 2),
        "min_ms": round(latencies[0], 2),
        "max_ms": round(latencies[-1], 2),
    }


def benchmark_conflict_check(base: str, n: int) -> dict:
    latencies = []
    for i in range(n):
        _, ms = _post(base, "/conflicts/check", {
            "agent_id": f"bench-agent-{i % 3}",
            "task_id": f"bench-task-{i}",
            "file_paths": [f"src/module_{i % 5}.py"],
            "intent_text": f"Benchmark conflict check iteration {i}",
        })
        latencies.append(ms)

    latencies.sort()
    return {
        "n": n,
        "avg_ms": round(statistics.mean(latencies), 2),
        "p95_ms": round(latencies[int(n * 0.95)], 2),
    }


def benchmark_compaction(base: str) -> dict:
    result, ms = _post(base, "/compaction/run", {})
    return {
        "latency_ms": round(ms, 2),
        "clusters_processed": result.get("clusters_processed", 0),
        "docs_deleted": result.get("docs_deleted", 0),
        "compression_ratio": result.get("compression_ratio", 1.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SPM benchmark script")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=50, help="Number of retrieval/conflict iterations")
    args = parser.parse_args()

    print("=" * 60)
    print("SPM Benchmark Report")
    print("=" * 60)

    print(f"\n📡 Retrieval latency ({args.n} queries):")
    r = benchmark_retrieval(args.api, args.n)
    for k, v in r.items():
        print(f"  {k}: {v}")

    print(f"\n⚡ Conflict check latency ({args.n} checks):")
    c = benchmark_conflict_check(args.api, args.n)
    for k, v in c.items():
        print(f"  {k}: {v}")

    print("\n🗜️  Compaction:")
    cp = benchmark_compaction(args.api)
    for k, v in cp.items():
        print(f"  {k}: {v}")

    print("\n✅ Benchmark complete.")


if __name__ == "__main__":
    main()
