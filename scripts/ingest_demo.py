"""
Scripted 3-agent demo scenario.

Usage:
    python scripts/ingest_demo.py               # real API calls to http://localhost:8000
    python scripts/ingest_demo.py --dry-run     # print what would happen, no calls
    python scripts/ingest_demo.py --base-url http://myserver:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any


BASE_URL = "http://localhost:8000"


def _print(emoji: str, msg: str) -> None:
    print(f"{emoji}  {msg}", flush=True)


def _post(path: str, payload: dict, dry_run: bool, base_url: str) -> dict:
    if dry_run:
        _print("📤", f"POST {path}  {json.dumps(payload, indent=2)}")
        return {"record_id": f"dry-run:{path}", "status": "dry_run", "conflicts": [], "risk_score": 0.0}
    import httpx
    resp = httpx.post(f"{base_url}{path}", json=payload, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def _patch(path: str, payload: dict, dry_run: bool, base_url: str) -> dict:
    if dry_run:
        _print("📤", f"PATCH {path}  {json.dumps(payload)}")
        return {"success": True, "status": payload.get("new_status", "done")}
    import httpx
    resp = httpx.patch(f"{base_url}{path}", json=payload, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def _get(path: str, dry_run: bool, base_url: str) -> dict:
    if dry_run:
        _print("📥", f"GET {path}")
        return {"order": [], "claims": []}
    import httpx
    resp = httpx.get(f"{base_url}{path}", timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def run_demo(dry_run: bool, base_url: str) -> None:
    project_id = "demo-project"
    workspace_id = "shared"

    print("\n" + "=" * 60)
    print("  SPM — 3-Agent Coordination Demo")
    print("=" * 60 + "\n")

    # ------------------------------------------------------------------
    # Step 1: Agent A claims auth refactor
    # ------------------------------------------------------------------
    _print("🤖", "Step 1: Agent A claims auth refactor (login.py, session.py)")
    claim_a = _post(
        "/claims",
        {
            "agent_id": "agent-a",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "task_description": "Refactor authentication: modernize login flow, improve session management",
            "file_paths": ["src/auth/login.py", "src/auth/session.py"],
            "dependencies": [],
        },
        dry_run=dry_run,
        base_url=base_url,
    )
    record_id_a = claim_a.get("record_id", "unknown")
    _print("✅", f"Agent A claimed task: {record_id_a} (status={claim_a.get('status')})")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 2: Agent A records plan steps
    # ------------------------------------------------------------------
    _print("📝", "Step 2: Agent A records plan steps")
    for step_num, step_text in enumerate(
        [
            "Audit existing login.py for security issues",
            "Implement JWT token rotation in session.py",
            "Add rate limiting to login endpoint",
            "Write migration script for existing sessions",
        ],
        start=1,
    ):
        result = _post(
            "/plan-steps",
            {
                "agent_id": "agent-a",
                "project_id": project_id,
                "workspace_id": workspace_id,
                "step_text": step_text,
                "task_id": record_id_a,
                "step_number": step_num,
                "total_steps": 4,
            },
            dry_run=dry_run,
            base_url=base_url,
        )
        _print("  📌", f"Step {step_num}/4: {step_text[:60]}")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 3: Agent B proposes DB optimization touching session.py → conflict!
    # ------------------------------------------------------------------
    _print("🤖", "Step 3: Agent B claims DB optimization (session.py) — conflict expected!")
    claim_b = _post(
        "/claims",
        {
            "agent_id": "agent-b",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "task_description": "Optimize database queries in session management layer",
            "file_paths": ["src/auth/session.py", "src/db/models.py"],
            "dependencies": [],
        },
        dry_run=dry_run,
        base_url=base_url,
    )
    record_id_b = claim_b.get("record_id", "unknown")
    status_b = claim_b.get("status", "unknown")
    risk = claim_b.get("risk_score", 0.0)
    _print(
        "⚠️" if status_b in ("blocked", "queued") else "✅",
        f"Agent B status: {status_b} | Risk score: {risk:.2f} | Recommendation: {claim_b.get('recommendation')}",
    )
    if claim_b.get("conflicts"):
        _print("🔍", f"Conflicts detected with: {[c['id'] for c in claim_b['conflicts']]}")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 4: Get execution order
    # ------------------------------------------------------------------
    _print("📊", "Step 4: System suggests execution order")
    order_data = _get(f"/execution-order/{project_id}/{workspace_id}", dry_run=dry_run, base_url=base_url)
    order = order_data.get("order", [])
    if order:
        for i, item in enumerate(order, 1):
            _print("  🔢", f"{i}. {item['agent_id']} — {item.get('task_description', '')[:50]} ({item['status']})")
    else:
        _print("  ℹ️", "No active claims in execution order (dry-run or empty)")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 5: Agent C queries shared memory
    # ------------------------------------------------------------------
    _print("🤖", "Step 5: Agent C queries — 'What's the current plan for authentication?'")
    query_result = _post(
        "/query",
        {
            "question": "What is the current plan for authentication?",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "agent_id": "agent-c",
        },
        dry_run=dry_run,
        base_url=base_url,
    )
    _print("💬", "Answer:")
    answer = query_result.get("answer", "(no answer)")
    for line in answer.split("\n")[:8]:
        if line.strip():
            print(f"     {line}")
    sources = query_result.get("sources", [])
    _print("📚", f"Grounded in {len(sources)} memory record(s)")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 6: Agent A records a decision
    # ------------------------------------------------------------------
    _print("📝", "Step 6: Agent A records architectural decision")
    decision = _post(
        "/decisions",
        {
            "agent_id": "agent-a",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "decision_text": "Use stateless JWT tokens with 1h expiry. Session data stored in Redis, not DB. This unblocks Agent B's DB optimization.",
            "task_id": record_id_a,
            "affected_files": ["src/auth/login.py", "src/auth/session.py"],
        },
        dry_run=dry_run,
        base_url=base_url,
    )
    _print("✅", f"Decision recorded: {decision.get('record_id', 'unknown')}")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 7: Agent A completes task
    # ------------------------------------------------------------------
    _print("🤖", "Step 7: Agent A marks task as done")
    update_a = _patch(
        f"/claims/{record_id_a}",
        {"new_status": "done", "agent_id": "agent-a"},
        dry_run=dry_run,
        base_url=base_url,
    )
    _print("✅", f"Agent A task status: {update_a.get('status', 'done')}")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 8: Agent A merges workspace
    # ------------------------------------------------------------------
    _print("🔀", "Step 8: Agent A merges workspace to shared")
    merge = _post(
        "/merge",
        {
            "agent_id": "agent-a",
            "project_id": project_id,
            "source_workspace": workspace_id,
            "target_workspace": "main",
            "files_changed": ["src/auth/login.py", "src/auth/session.py"],
        },
        dry_run=dry_run,
        base_url=base_url,
    )
    _print("✅", f"Merge complete: {merge.get('record_id', 'unknown')}")
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 9: Agent B proceeds
    # ------------------------------------------------------------------
    _print("🤖", "Step 9: Agent B updates status to in_progress")
    update_b = _patch(
        f"/claims/{record_id_b}",
        {"new_status": "in_progress", "agent_id": "agent-b"},
        dry_run=dry_run,
        base_url=base_url,
    )
    _print("✅", f"Agent B task status: {update_b.get('status', 'in_progress')}")

    print("\n" + "=" * 60)
    print("  Demo complete! ✨")
    print(f"  Records written to project: {project_id}")
    print("  Run compaction at: POST /compact")
    print("  View dashboard at:  http://localhost:8501")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="SPM 3-Agent Demo")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without making API calls",
    )
    parser.add_argument("--base-url", default=BASE_URL, help="API base URL")
    args = parser.parse_args()
    run_demo(dry_run=args.dry_run, base_url=args.base_url)


if __name__ == "__main__":
    main()
