"""
Demo ingestion script — scripted 3-agent scenario.

Simulates Agent A, B, and C interacting with the SPM API to demonstrate:
  1. Task claiming
  2. Conflict detection (Agent B → blocked on session.py)
  3. Execution ordering
  4. Context query (Agent C → grounded answer)
  5. Task completion and merge

Usage:
    python scripts/ingest_demo.py --api http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def _post(base: str, path: str, payload: dict) -> dict:
    resp = httpx.post(f"{base}{path}", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _delete(base: str, path: str, payload: dict) -> dict:
    resp = httpx.request("DELETE", f"{base}{path}", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _get(base: str, path: str) -> dict:
    resp = httpx.get(f"{base}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def run_demo(base: str) -> None:
    print("=" * 60)
    print("SPM Demo — 3-Agent Scenario")
    print("=" * 60)

    # ── Step 1: Agent A claims auth refactor ──────────────────────────────────
    print("\n[1] Agent A claims auth refactor task…")
    result = _post(base, "/claims/auth-refactor", {
        "agent_id": "agent-a",
        "task_id": "auth-refactor",
        "description": "Refactor authentication: extract JWT logic from login.py and session.py",
        "file_paths": ["src/auth/login.py", "src/auth/session.py"],
        "priority": 4,
    })
    print(f"    → status={result['status']} message={result['message']}")

    # ── Step 2: Agent A records architectural decision ────────────────────────
    print("\n[2] Agent A records an architectural decision…")
    _post(base, "/decisions", {
        "agent_id": "agent-a",
        "decision_text": "Use stateless JWT tokens for all session management. Remove server-side session store.",
        "rationale": "Reduces DB load, simplifies horizontal scaling, aligns with API-first architecture.",
        "affected_files": ["src/auth/login.py", "src/auth/session.py", "src/auth/tokens.py"],
    })
    print("    → Decision stored.")

    time.sleep(1)

    # ── Step 3: Agent B attempts to claim session optimization ────────────────
    print("\n[3] Agent B attempts to claim DB session optimization (CONFLICT expected)…")
    try:
        result_b = _post(base, "/claims/db-session-opt", {
            "agent_id": "agent-b",
            "task_id": "db-session-opt",
            "description": "Optimise database queries in session management module",
            "file_paths": ["src/auth/session.py", "src/db/connection.py"],
            "priority": 3,
        })
        print(f"    → status={result_b['status']} message={result_b['message']}")
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", {})
        conflict = detail.get("conflict", {})
        print(f"    → BLOCKED: {detail.get('message', '')}")
        print(f"       risk_score={conflict.get('risk_score', 'n/a')}")
        print(f"       channel_scores={conflict.get('channel_scores', {})}")
        print(f"       recommendation={conflict.get('recommendation', '')}")

    # ── Step 4: Suggest execution order ───────────────────────────────────────
    print("\n[4] Requesting suggested execution order…")
    order = _post(base, "/conflicts/suggest-order", {
        "agent_a": "agent-a",
        "task_a": "auth-refactor",
        "agent_b": "agent-b",
        "task_b": "db-session-opt",
    })
    for i, step in enumerate(order["recommended_order"], 1):
        print(f"    {i}. {step['agent']} → {step['task']}")
    print(f"    Rationale: {order['rationale']}")

    time.sleep(1)

    # ── Step 5: Agent C asks a context question ───────────────────────────────
    print("\n[5] Agent C asks: 'What is the current plan for authentication?'")
    ctx = _post(base, "/context/query", {
        "question": "What is the current plan for authentication?",
        "agent_id": "agent-c",
        "top_k": 5,
        "use_shared": True,
    })
    print(f"    → Answer: {ctx['answer'][:300]}")
    print(f"    → Citations: {ctx['citations']}")

    # ── Step 6: Agent A completes its task ────────────────────────────────────
    print("\n[6] Agent A completes and merges the auth refactor…")
    result_done = _delete(base, "/claims/auth-refactor", {
        "agent_id": "agent-a",
        "merged_files": ["src/auth/login.py", "src/auth/session.py", "src/auth/tokens.py"],
        "merge_summary": "Extracted JWT logic into tokens.py; session.py now delegates to tokens module.",
    })
    print(f"    → {result_done['message']}")

    # ── Step 7: Memory stats before compaction ────────────────────────────────
    print("\n[7] Memory stats before compaction…")
    stats = _get(base, "/context/stats")
    print(f"    → Total records: {stats['total_records']}")

    # ── Step 8: Run compaction ────────────────────────────────────────────────
    print("\n[8] Running compaction…")
    compact = _post(base, "/compaction/run", {})
    print(f"    → clusters_processed={compact['clusters_processed']}")
    print(f"    → docs_deleted={compact['docs_deleted']}")
    print(f"    → compression_ratio={compact['compression_ratio']:.2f}x")

    # ── Step 9: Repeat context query post-compaction ──────────────────────────
    print("\n[9] Agent C repeats query post-compaction…")
    ctx2 = _post(base, "/context/query", {
        "question": "What is the current plan for authentication?",
        "agent_id": "agent-c",
        "top_k": 5,
        "use_shared": True,
    })
    print(f"    → Answer: {ctx2['answer'][:300]}")
    print(f"    → Citations: {ctx2['citations']}")

    # ── Step 10: Final metrics ────────────────────────────────────────────────
    print("\n[10] Final metrics…")
    m = _get(base, "/metrics")
    conflict = m.get("conflict", {})
    retrieval = m.get("retrieval", {})
    compaction = m.get("compaction", {})
    print(f"    Conflicts: proceed={conflict.get('proceed_count',0)} "
          f"warn={conflict.get('warn_count',0)} block={conflict.get('block_count',0)}")
    print(f"    Retrieval avg latency: {retrieval.get('avg_latency_ms',0):.1f}ms")
    print(f"    Compaction runs: {compaction.get('runs',0)} "
          f"avg_ratio={compaction.get('avg_compression_ratio',1.0):.2f}x")

    print("\n✅ Demo complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="SPM demo ingestion script")
    parser.add_argument(
        "--api", default="http://localhost:8000", help="SPM API base URL"
    )
    args = parser.parse_args()
    run_demo(args.api)


if __name__ == "__main__":
    main()
