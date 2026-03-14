"""
End-to-end demo runner.

Starts API server, runs ingest_demo.py, compaction, and benchmark, then prints
final metrics summary.
"""

from __future__ import annotations

import atexit
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
API_URL = "http://localhost:8000"
STARTUP_TIMEOUT = 30  # seconds


def _wait_for_api(timeout: int = STARTUP_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API_URL}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    return False


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n>>> {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(ROOT), check=check)
    return result


def main() -> None:
    # ------------------------------------------------------------------
    # Start API server
    # ------------------------------------------------------------------
    print("🚀 Starting SPM API server...")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "src.main", "--port", "8000"],
        cwd=str(ROOT),
    )

    def _cleanup():
        print("\n🧹 Shutting down API server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()

    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    print(f"⏳ Waiting for API server at {API_URL}...")
    if not _wait_for_api():
        print("❌ API server failed to start within timeout")
        sys.exit(1)
    print("✅ API server is ready\n")

    # ------------------------------------------------------------------
    # Run demo scenario
    # ------------------------------------------------------------------
    print("=" * 60)
    print("  Phase 1: Running 3-agent demo scenario")
    print("=" * 60)
    _run([sys.executable, "scripts/ingest_demo.py", "--base-url", API_URL])

    # ------------------------------------------------------------------
    # Run compaction
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  Phase 2: Triggering compaction")
    print("=" * 60)
    try:
        resp = httpx.post(
            f"{API_URL}/compact",
            json={"project_id": "demo-project", "workspace_id": "shared"},
            timeout=30.0,
        )
        resp.raise_for_status()
        compact_result = resp.json()
        print(f"  Records before: {compact_result['records_before']}")
        print(f"  Records after:  {compact_result['records_after']}")
        print(f"  Compression:    {compact_result['compression_ratio']:.2f}x")
        print(f"  Duration:       {compact_result['duration_seconds']:.2f}s")
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ Compaction failed: {exc}")

    # ------------------------------------------------------------------
    # Run benchmark
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  Phase 3: Running benchmark")
    print("=" * 60)
    _run([sys.executable, "scripts/benchmark.py", "--base-url", API_URL], check=False)

    # ------------------------------------------------------------------
    # Final metrics summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  Final Metrics Summary")
    print("=" * 60)
    try:
        resp = httpx.get(f"{API_URL}/metrics", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        metrics = data.get("metrics", {})
        print(f"  Total operations:       {metrics.get('total_operations', 0)}")
        print(f"  Avg compression ratio:  {metrics.get('avg_compression_ratio', 0):.2f}x")
        print(f"  Avg grounding rate:     {metrics.get('avg_grounding_rate', 0):.1%}")
        print(f"  Conflict prevention:    {metrics.get('conflict_prevention_rate', 0):.1%}")
        print(f"  Conflicts prevented:    {metrics.get('conflict_prevention_count', 0)}")

        by_op = metrics.get("latency_by_operation", {})
        if by_op:
            print("\n  Latency by Operation:")
            print(f"  {'Operation':<25} {'p50':>6} {'p95':>6} {'p99':>6}  (ms)")
            print("  " + "-" * 48)
            for op, stats in by_op.items():
                print(f"  {op:<25} {stats['p50']:>6.1f} {stats['p95']:>6.1f} {stats['p99']:>6.1f}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ Could not fetch metrics: {exc}")

    print("\n✨ Demo complete!")
    print(f"   Dashboard: http://localhost:8501")
    print(f"   API docs:  {API_URL}/docs\n")


if __name__ == "__main__":
    main()
