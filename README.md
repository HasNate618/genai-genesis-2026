# 🧠 Shared Project Memory (SPM)

> **Multi-agent coordination layer powered by Moorcheh semantic memory.**
> GenAI Genesis 2026 — targeting Bitdeer "Beyond the Prototype" + Moorcheh "Efficient Memory" prize tracks.

---

## What It Does

SPM is a coordination middleware that lets multiple AI coding agents (Cursor, Windsurf, Aider, Devin, etc.) work on the same codebase **without conflicts**. It gives every agent a shared, searchable memory of what every other agent is doing, has decided, and has changed — backed by Moorcheh's 32× compressed vector store.

```
┌─────────┐  ┌─────────┐  ┌─────────┐
│ Agent A │  │ Agent B │  │ Agent C │
└────┬────┘  └────┬────┘  └────┬────┘
     │             │             │
     └─────────────┴─────────────┘
                   │  HTTP REST
          ┌────────▼────────┐
          │  SPM FastAPI     │
          │  Coordination    │
          │  Conflict Detect │
          │  Compaction      │
          └────────┬────────┘
          ┌────────▼────────┐
          │ Moorcheh (MIB)  │  ← 32× storage compression
          │  Semantic Search │  ← Deterministic exhaustive search
          └─────────────────┘
          ┌─────────────────┐
          │ SQLite Index     │  ← Fast exact lookups
          └─────────────────┘
```

---

## Architecture Overview

| Component | File | Responsibility |
|---|---|---|
| FastAPI Server | `src/api/server.py` | All HTTP endpoints for agents |
| Pydantic Models | `src/api/models.py` | Request/response schemas |
| Dependency Injection | `src/api/deps.py` | Singleton wiring |
| Coordination Engine | `src/core/coordination.py` | Task claiming, merge protocols |
| Conflict Detector | `src/core/conflict.py` | 3-channel conflict detection |
| Compactor | `src/core/compactor.py` | Memory compaction + LLM summarization |
| Memory Store | `src/memory/store.py` | Moorcheh client wrapper + fallback |
| SQLite Index | `src/memory/index.py` | Deterministic exact-match index |
| Memory Schemas | `src/memory/schemas.py` | MemoryRecord dataclass |
| Metrics Collector | `src/metrics/collector.py` | Latency, compression, conflict stats |
| Streamlit Dashboard | `src/ui/app.py` | Real-time observability UI |

---

## Project Structure

```
src/
  api/
    server.py          # FastAPI app, all routes, middleware
    models.py          # Pydantic request/response schemas
    deps.py            # Dependency injection (singletons)
  core/
    coordination.py    # Task claim, execution ordering
    conflict.py        # Three-channel conflict detection
    compactor.py       # Compaction loop + LLM summarizer
  memory/
    store.py           # Moorcheh client wrapper + offline fallback
    index.py           # SQLite deterministic index
    schemas.py         # MemoryRecord dataclass + type payloads
  metrics/
    collector.py       # Latency, compression, grounding tracking
    dashboard.py       # Metrics aggregation for UI
  ui/
    app.py             # Streamlit dashboard
  config.py            # pydantic-settings configuration
  main.py              # Uvicorn entrypoint
scripts/
  ingest_demo.py       # Scripted 3-agent demo scenario
  run_demo.py          # End-to-end demo runner (starts server + demo)
  benchmark.py         # Latency + compression benchmark script
tests/
  conftest.py          # Shared fixtures, mocked Moorcheh client
  test_store.py        # MemoryStore unit tests
  test_coordination.py # CoordinationEngine unit tests
  test_conflict.py     # ConflictDetector unit tests
  test_compactor.py    # Compactor unit tests
Dockerfile
docker-compose.yml
requirements.txt
.env.example
```

---

## Conflict Detection

Three channels, weighted composite score:

| Channel | Weight | Method |
|---|---|---|
| File path overlap | 0.50 | SQLite exact-match query |
| Dependency overlap | 0.30 | SQLite dependency_edge records |
| Semantic overlap | 0.20 | Moorcheh similarity search |

- **score ≥ 0.7** → Block + re-plan
- **score 0.4–0.69** → Warn + suggest order
- **score < 0.4** → Proceed

---

## Memory Compaction

Compaction keeps memory footprint bounded:
1. Cluster done/low-importance records by task or topic
2. Summarize each cluster via LLM (OpenAI / Anthropic / rule-based fallback)
3. Upload summary to Moorcheh (importance=5, never re-compacted)
4. Delete raw records
5. Log compression ratio

On top of Moorcheh's 32× storage compression, SPM targets an additional **5–10×** application-level compaction ratio.

---

## Quick Start

```bash
# 1. Clone and install
git clone <repo>
cd genai-genesis-2026
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set MOORCHEH_API_KEY and OPENAI_API_KEY

# 3. Start API server
python -m src.main

# 4. Start dashboard (separate terminal)
streamlit run src/ui/app.py

# 5. Run demo
python scripts/run_demo.py

# 6. Run benchmarks
python scripts/benchmark.py --n 50
```

### Docker

```bash
cp .env.example .env   # fill in API keys
docker-compose up --build
# API: http://localhost:8000
# Dashboard: http://localhost:8501
```

---

## API Reference

The API is self-documenting via OpenAPI: visit `http://localhost:8000/docs` after starting the server.

| Method | Path | Description |
|---|---|---|
| `POST` | `/claims/{task_id}` | Claim a task (runs conflict check) |
| `DELETE` | `/claims/{task_id}` | Release a task (mark done + merge) |
| `POST` | `/intents` | Register a file-change intent |
| `POST` | `/decisions` | Store an architectural decision |
| `POST` | `/conflicts/check` | Run 3-channel conflict detection |
| `POST` | `/conflicts/suggest-order` | Get recommended execution order |
| `POST` | `/context/query` | Natural-language query with grounded answer |
| `GET` | `/context/stats` | Memory statistics |
| `POST` | `/compaction/run` | Trigger compaction |
| `GET` | `/metrics` | Latency, conflict, compaction stats |
| `GET` | `/health` | Health check |

---

## Running Tests

```bash
pytest
```

Tests use an in-memory SQLite index and a mocked Moorcheh client — no network required.

---

## Key Dependencies

| Package | Purpose |
|---|---|
| `moorcheh-sdk` | Core semantic memory layer |
| `fastapi` + `uvicorn` | REST API server |
| `pydantic` + `pydantic-settings` | Schemas + config |
| `streamlit` | Dashboard UI |
| `openai` / `anthropic` | LLM for compaction summaries |
| `structlog` | Structured JSON logging |
| `pytest` + `httpx` | Testing |

---

## Why Moorcheh

- **32× storage compression** via MIB (Maximally Informative Binarization) — essential for retaining weeks of multi-agent history in bounded memory
- **Deterministic exhaustive search** via ITS scoring — conflict detection cannot afford to miss results
- **Grounded answers with citations** — every answer cites specific memory records by ID and timestamp, enabling full auditability
