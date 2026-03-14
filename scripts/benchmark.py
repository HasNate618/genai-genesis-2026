"""
Benchmark script: measures latency percentiles and compression ratios.

Usage:
    python scripts/benchmark.py
    python scripts/benchmark.py --iterations 100 --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8000"
PROJECT_ID = "benchmark-project"
WORKSPACE_ID = "shared"


def _post(client: httpx.Client, path: str, payload: dict) -> tuple[dict, float]:
    start = time.perf_counter()
    resp = client.post(path, json=payload, timeout=15.0)
    duration_ms = (time.perf_counter() - start) * 1000
    resp.raise_for_status()
    return resp.json(), duration_ms


def _get(client: httpx.Client, path: str) -> tuple[dict, float]:
    start = time.perf_counter()
    resp = client.get(path, timeout=10.0)
    duration_ms = (time.perf_counter() - start) * 1000
    resp.raise_for_status()
    return resp.json(), duration_ms


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


def _print_table(title: str, rows: list[dict]) -> None:
    if not rows:
        return
    headers = list(rows[0].keys())
    widths = {h: max(len(h), max(len(str(r[h])) for r in rows)) for h in headers}
    sep = "  ".join("-" * widths[h] for h in headers)
    header_row = "  ".join(h.ljust(widths[h]) for h in headers)
    print(f"\n  {title}")
    print(f"  {sep}")
    print(f"  {header_row}")
    print(f"  {sep}")
    for r in rows:
        print("  " + "  ".join(str(r[h]).ljust(widths[h]) for h in headers))
    print(f"  {sep}")


def run_benchmark(base_url: str, n: int) -> None:
    print(f"\n{'=' * 60}")
    print(f"  SPM Benchmark  ({n} iterations)")
    print(f"  Target: {base_url}")
    print(f"{'=' * 60}")

    latencies: dict[str, list[float]] = {
        "claim_task": [],
        "record_plan_step": [],
        "record_decision": [],
        "query_context": [],
        "compact": [],
    }
    record_ids: list[str] = []

    with httpx.Client(base_url=base_url) as client:
        # Check health
        try:
            health, _ = _get(client, "/health")
            if health.get("status") not in ("ok", "degraded"):
                print("❌ API not healthy")
                return
            print(f"  ✅ API status: {health['status']}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ API unreachable: {exc}")
            return

        # Seed some records
        print(f"  Seeding {n} claims + plan steps...")
        for i in range(n):
            result, ms = _post(
                client,
                "/claims",
                {
                    "agent_id": f"bench-agent-{i % 5}",
                    "project_id": PROJECT_ID,
                    "workspace_id": WORKSPACE_ID,
                    "task_description": f"Benchmark task {i}: refactor module_{i % 10}",
                    "file_paths": [f"src/module_{i % 10}.py", f"src/util_{i % 7}.py"],
                },
            )
            latencies["claim_task"].append(ms)
            if result.get("record_id"):
                record_ids.append(result["record_id"])

            step_result, ms = _post(
                client,
                "/plan-steps",
                {
                    "agent_id": f"bench-agent-{i % 5}",
                    "project_id": PROJECT_ID,
                    "workspace_id": WORKSPACE_ID,
                    "step_text": f"Implement feature {i} in module_{i % 10}",
                    "task_id": result.get("record_id", ""),
                    "step_number": 1,
                    "total_steps": 3,
                },
            )
            latencies["record_plan_step"].append(ms)

        print(f"  Seeded {len(record_ids)} records.\n")

        # Decision recording
        for i in range(min(n, 20)):
            if i < len(record_ids):
                _, ms = _post(
                    client,
                    "/decisions",
                    {
                        "agent_id": f"bench-agent-{i % 5}",
                        "project_id": PROJECT_ID,
                        "workspace_id": WORKSPACE_ID,
                        "decision_text": f"Use pattern X for module_{i % 10} based on analysis",
                        "task_id": record_ids[i],
                        "affected_files": [f"src/module_{i % 10}.py"],
                    },
                )
                latencies["record_decision"].append(ms)

        # Query latency
        print("  Running query benchmark...")
        queries = [
            "What modules are being refactored?",
            "Which agents are working on authentication?",
            "What decisions have been made about the database?",
            "What is the current execution plan?",
            "Are there any conflicts in the current workspace?",
        ]
        for q in queries * max(1, n // 5):
            _, ms = _post(
                client,
                "/query",
                {
                    "question": q,
                    "project_id": PROJECT_ID,
                    "workspace_id": WORKSPACE_ID,
                    "agent_id": "benchmark",
                },
            )
            latencies["query_context"].append(ms)

        # Mark records done for compaction
        print("  Marking records done for compaction test...")
        for rid in record_ids[:min(len(record_ids), n)]:
            try:
                client.patch(
                    f"/claims/{rid}",
                    json={"new_status": "done", "agent_id": "benchmark"},
                    timeout=5.0,
                )
            except Exception:  # noqa: BLE001
                pass

        # Compaction benchmark
        print("  Running compaction...")
        compact_result, ms = _post(
            client,
            "/compact",
            {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
        )
        latencies["compact"].append(ms)
        compression_ratio = compact_result.get("compression_ratio", 1.0)
        records_before = compact_result.get("records_before", 0)
        records_after = compact_result.get("records_after", 0)

    # ------------------------------------------------------------------
    # Print results
    # ------------------------------------------------------------------
    rows = []
    for op, times in latencies.items():
        if times:
            rows.append(
                {
                    "Operation": op,
                    "N": len(times),
                    "p50 (ms)": f"{_percentile(times, 50):.1f}",
                    "p95 (ms)": f"{_percentile(times, 95):.1f}",
                    "p99 (ms)": f"{_percentile(times, 99):.1f}",
                    "Mean (ms)": f"{statistics.mean(times):.1f}",
                }
            )

    _print_table("Latency Percentiles", rows)

    print(f"\n  Compaction Results:")
    print(f"    Records before:     {records_before}")
    print(f"    Records after:      {records_after}")
    print(f"    Compression ratio:  {compression_ratio:.2f}x")
    print(f"    Compaction time:    {latencies['compact'][0]:.1f}ms\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="SPM Benchmark")
    parser.add_argument("--iterations", "-n", type=int, default=20)
    parser.add_argument("--base-url", default=DEFAULT_URL)
    args = parser.parse_args()
    run_benchmark(base_url=args.base_url, n=args.iterations)


if __name__ == "__main__":
    main()
