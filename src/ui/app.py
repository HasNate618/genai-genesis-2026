"""
SPM Streamlit dashboard.

Run with: streamlit run src/ui/app.py
"""

from __future__ import annotations

import time

import httpx
import streamlit as st

API_BASE = "http://localhost:8000"
REFRESH_INTERVAL = 10  # seconds


def _get(path: str, **params) -> dict:
    try:
        resp = httpx.get(f"{API_BASE}{path}", params=params, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _post(path: str, payload: dict) -> dict:
    try:
        resp = httpx.post(f"{API_BASE}{path}", json=payload, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _truncate(text: str, max_len: int = 60) -> str:
    return text[:max_len] + ("..." if len(text) > max_len else "")


def main() -> None:
    st.set_page_config(
        page_title="SPM — Shared Agent Memory Layer",
        page_icon="🧠",
        layout="wide",
    )

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.title("🧠 SPM Controls")
        project_id = st.text_input("Project ID", value="demo-project")
        workspace_id = st.text_input("Workspace ID", value="shared")
        refresh = st.button("🔄 Refresh Now")
        compact_btn = st.button("🗜️ Run Compaction")

        if compact_btn:
            with st.spinner("Compacting..."):
                result = _post(
                    "/compact",
                    {"project_id": project_id, "workspace_id": workspace_id},
                )
                if "error" not in result:
                    st.success(
                        f"Compacted {result['records_before']} → {result['records_after']} records "
                        f"(ratio: {result['compression_ratio']:.2f}x)"
                    )
                else:
                    st.error(result["error"])

        st.markdown("---")
        st.caption("Auto-refreshes every 10 seconds")

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    st.title("🧠 SPM — Shared Agent Memory Layer")
    st.caption("Real-time multi-agent coordination dashboard")

    health = _get("/health")
    if health.get("status") == "ok":
        st.success("✅ API server healthy")
    elif "error" in health:
        st.error(f"❌ API unreachable: {health['error']}")
        st.stop()
    else:
        st.warning(f"⚠️ API degraded: {health.get('status')}")

    # -----------------------------------------------------------------------
    # Section 1: Active Claims
    # -----------------------------------------------------------------------
    st.header("📋 Active Claims")
    claims_data = _get(f"/claims/{project_id}")
    claims = claims_data.get("claims", [])
    active_claims = [c for c in claims if c["status"] not in ("done", "superseded")]

    if active_claims:
        rows = []
        for c in active_claims:
            rows.append(
                {
                    "Agent": c["agent_id"],
                    "Task": _truncate(c["task_description"]),
                    "Status": c["status"],
                    "Files": ", ".join(c["file_paths"][:3]),
                    "Importance": c["importance"],
                    "Timestamp": c["timestamp"][:19],
                }
            )
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("No active claims.")

    # -----------------------------------------------------------------------
    # Section 2: Conflict Alerts
    # -----------------------------------------------------------------------
    st.header("⚠️ Conflict Alerts")
    conflicts_data = _get(f"/conflicts/{project_id}")
    alerts = conflicts_data.get("alerts", [])

    if alerts:
        for alert in alerts[:10]:
            risk = alert["risk_score"]
            if risk >= 0.7:
                color = "🔴"
            elif risk >= 0.4:
                color = "🟡"
            else:
                color = "🟢"
            with st.expander(
                f"{color} Risk {risk:.2f} — {alert['recommendation'].upper()} ({alert['timestamp'][:19]})"
            ):
                st.write(alert["text"])
                channels = alert.get("channels", {})
                if channels:
                    cols = st.columns(len(channels))
                    for col, (ch, score) in zip(cols, channels.items()):
                        col.metric(ch.replace("_", " ").title(), f"{score:.2f}")
    else:
        st.info("No conflict alerts.")

    # -----------------------------------------------------------------------
    # Section 3: Memory Stats
    # -----------------------------------------------------------------------
    st.header("💾 Memory Statistics")
    # Fetch from metrics endpoint
    metrics_data = _get("/metrics")
    index_stats = metrics_data.get("index_stats", {})
    summary_stats = metrics_data.get("metrics", {})

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Records", index_stats.get("claims_count", 0))
    col2.metric("File Intents", index_stats.get("file_intents_count", 0))
    col3.metric(
        "Avg Compression",
        f"{summary_stats.get('avg_compression_ratio', 1.0):.1f}x",
    )
    col4.metric("Total Operations", summary_stats.get("total_operations", 0))

    # -----------------------------------------------------------------------
    # Section 4: Latency Histogram
    # -----------------------------------------------------------------------
    st.header("⏱️ Latency Histogram")
    histogram = metrics_data.get("latency_histogram", {})
    buckets = histogram.get("buckets", [])
    counts = histogram.get("counts", [])

    if buckets and any(c > 0 for c in counts):
        import pandas as pd

        df = pd.DataFrame({"Bucket (ms)": buckets, "Requests": counts})
        st.bar_chart(df.set_index("Bucket (ms)"))
    else:
        st.info("No latency data yet. Make some API calls first.")

    latency_by_op = summary_stats.get("latency_by_operation", {})
    if latency_by_op:
        st.subheader("Latency by Operation")
        op_rows = []
        for op, stats in latency_by_op.items():
            op_rows.append(
                {
                    "Operation": op,
                    "Count": stats["count"],
                    "p50 (ms)": stats["p50"],
                    "p95 (ms)": stats["p95"],
                    "p99 (ms)": stats["p99"],
                    "Mean (ms)": stats["mean"],
                }
            )
        st.dataframe(op_rows, use_container_width=True)

    # -----------------------------------------------------------------------
    # Section 5: Query Console
    # -----------------------------------------------------------------------
    st.header("🔍 Query Console")
    question = st.text_input(
        "Ask a question about the shared memory:",
        placeholder="What's the current plan for authentication?",
    )
    if st.button("🚀 Query") and question:
        with st.spinner("Querying memory..."):
            result = _post(
                "/query",
                {
                    "question": question,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "agent_id": "dashboard-user",
                },
            )
        if "error" in result:
            st.error(result["error"])
        else:
            st.markdown("**Answer:**")
            st.markdown(result.get("answer", "No answer."))
            sources = result.get("sources", [])
            if sources:
                with st.expander(f"📚 Sources ({len(sources)} records)"):
                    for s in sources:
                        st.markdown(
                            f"- `{s['record_id']}` ({s['record_type']}) "
                            f"by **{s['agent_id']}** at {s['timestamp'][:19]}"
                        )
                        st.caption(s["text"][:150])

    # -----------------------------------------------------------------------
    # Auto-refresh
    # -----------------------------------------------------------------------
    if not refresh:
        time.sleep(REFRESH_INTERVAL)
        st.rerun()


if __name__ == "__main__":
    main()
