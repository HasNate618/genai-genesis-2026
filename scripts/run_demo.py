"""
End-to-end demo runner.

Starts the SPM API server in a subprocess, waits for it to be ready,
runs the demo ingestion script, then tears down.

Usage:
    python scripts/run_demo.py
"""

from __future__ import annotations

import subprocess
import sys
import time

import httpx


def _wait_for_api(base: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main() -> None:
    api_base = "http://localhost:8000"
    print("Starting SPM API server…")
    server = subprocess.Popen(
        [sys.executable, "-m", "src.main"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_for_api(api_base):
            print("ERROR: API server did not start in time.")
            server.terminate()
            sys.exit(1)
        print("API server ready.\n")

        # Run the demo
        subprocess.run(
            [sys.executable, "scripts/ingest_demo.py", "--api", api_base],
            check=True,
        )
    finally:
        server.terminate()
        server.wait()
        print("\nAPI server stopped.")


if __name__ == "__main__":
    main()
