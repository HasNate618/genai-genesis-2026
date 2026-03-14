"""
Streamlit dashboard for the Shared Project Memory (SPM) system.

Run with:
    streamlit run src/ui/app.py

The dashboard shows:
  - Service health (Moorcheh + SQLite)
  - Active task claims
  - Conflict alerts
  - Memory statistics (total records, compression ratio)
  - Retrieval latency histogram
  - Query console for ad-hoc questions against shared memory
"""

from __future__ import annotations

import time

import httpx
import streamlit as st

API_BASE = st.sidebar.text_input("API base URL", value="http://localhost:8000")

st.set_page_config(
    page_title="SPM Dashboard",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 Shared Project Memory — Live Dashboard")

# ── Helper ────────────────────────────────────────────────────────────────────


def _get(path: str) -> dict:
    try:
        resp = httpx.get(f"{API_BASE}{path}", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def _post(path: str, payload: dict) -> dict:
    try:
        resp = httpx.post(f"{API_BASE}{path}", json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


# ── Auto-refresh ──────────────────────────────────────────────────────────────

refresh_interval = st.sidebar.slider("Auto-refresh (seconds)", 5, 60, 10)
if st.sidebar.button("🔄 Refresh now") or True:
    pass  # always re-render

# ── Row 1: Health + Stats ─────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)

health = _get("/health")
stats = _get("/context/stats")

with col1:
    st.subheader("Service Health")
    if "error" in health:
        st.error(f"API unreachable: {health['error']}")
    else:
        status_color = "🟢" if health.get("status") == "healthy" else "🟡"
        st.metric("Status", f"{status_color} {health.get('status', 'unknown').upper()}")
        st.metric("Moorcheh", "✅ Online" if health.get("moorcheh_available") else "⚠️ Offline (fallback)")
        st.metric("SQLite", "✅ OK" if health.get("sqlite_ok") else "❌ Error")

with col2:
    st.subheader("Memory Stats")
    if "error" in stats:
        st.warning(stats["error"])
    else:
        st.metric("Total Records", stats.get("total_records", "–"))
        st.metric("Project", stats.get("project_id", "–"))
        st.metric("Workspace", stats.get("workspace_id", "–"))

with col3:
    st.subheader("Quick Actions")
    if st.button("🗜️ Run Compaction"):
        result = _post("/compaction/run", {})
        if "error" in result:
            st.error(result["error"])
        else:
            st.success(
                f"Compacted {result.get('docs_deleted', 0)} records. "
                f"Ratio: {result.get('compression_ratio', 1.0):.2f}x"
            )

# ── Row 2: Metrics ────────────────────────────────────────────────────────────

st.divider()
metrics = _get("/metrics")

col4, col5, col6 = st.columns(3)

if "error" not in metrics:
    conflict = metrics.get("conflict", {})
    retrieval = metrics.get("retrieval", {})
    compaction = metrics.get("compaction", {})

    with col4:
        st.subheader("Conflict Stats")
        st.metric("✅ Proceeded", conflict.get("proceed_count", 0))
        st.metric("⚠️ Warned", conflict.get("warn_count", 0))
        st.metric("🚫 Blocked", conflict.get("block_count", 0))
        total = conflict.get("total", 0)
        blocked = conflict.get("block_count", 0)
        if total > 0:
            st.metric("Prevention Rate", f"{((total - blocked) / total * 100):.0f}%")

    with col5:
        st.subheader("Retrieval Latency")
        st.metric("Avg (ms)", f"{retrieval.get('avg_latency_ms', 0):.1f}")
        st.metric("P95 (ms)", f"{retrieval.get('p95_latency_ms', 0):.1f}")
        st.metric("Total Queries", retrieval.get("total_queries", 0))

    with col6:
        st.subheader("Compaction")
        st.metric("Runs", compaction.get("runs", 0))
        st.metric("Avg Ratio", f"{compaction.get('avg_compression_ratio', 1.0):.2f}x")
        st.metric("Total Deleted", compaction.get("total_docs_deleted", 0))

# ── Row 3: Query Console ──────────────────────────────────────────────────────

st.divider()
st.subheader("🔍 Query Console")

query = st.text_input(
    "Ask a question about the project memory:",
    placeholder="What is the current plan for authentication?",
)
top_k = st.slider("Top-K results", 1, 20, 5)

if st.button("Ask") and query:
    with st.spinner("Querying shared memory…"):
        result = _post(
            "/context/query",
            {"question": query, "top_k": top_k, "use_shared": True},
        )
    if "error" in result:
        st.error(result["error"])
    else:
        st.markdown(f"**Answer:** {result.get('answer', '')}")
        citations = result.get("citations", [])
        if citations:
            st.markdown(f"**Citations ({len(citations)}):** {', '.join(str(c) for c in citations)}")
        docs = result.get("retrieved_docs", [])
        if docs:
            with st.expander(f"Retrieved Documents ({len(docs)})"):
                for i, doc in enumerate(docs, 1):
                    st.markdown(f"**{i}.** {doc.get('text', str(doc))[:200]}")

# ── Auto-refresh footer ───────────────────────────────────────────────────────

st.caption(
    f"Last refreshed: {time.strftime('%H:%M:%S')}  |  "
    f"API: {API_BASE}  |  Auto-refresh every {refresh_interval}s"
)

# Use Streamlit's fragment-based auto-refresh so the main thread is not blocked
st.markdown(
    f'<meta http-equiv="refresh" content="{refresh_interval}">',
    unsafe_allow_html=True,
)
