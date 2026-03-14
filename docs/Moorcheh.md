# Moorcheh Vector Memory Integration (What Is Implemented + Real DB Usage)

This document describes the **exact implementation currently in this repository** for Moorcheh integration, and how to run it against a **real Moorcheh vector database**.


## Scope of What Was Implemented

The implementation is a **vector-only memory layer scaffold** for the multi-agent workflow. It includes:

- Config + env validation
- Embedding provider abstraction (mock + OpenAI-compatible)
- Moorcheh SDK client wrapper (namespace, vector upload, search, answer)
- Vector store facade with telemetry
- Canonical context record schema (deterministic IDs)
- Context write/read helpers for planner/coordinator
- Conflict compensation logic for task overlap reduction
- Async agent context contract
- FastAPI debug/ops endpoints
- Prize-track benchmark harness
- Unit/integration-style tests

Important boundary:

- The memory components are implemented and ready.
- Full orchestration-engine transition wiring is **not** implemented yet in this repo (no state machine runtime files were present to attach to directly).


## Files Added and What Each One Does

## Core backend entrypoints

- `backend/main.py`
  - Creates FastAPI app.
  - Mounts the memory router.

- `backend/api/routes.py`
  - Exposes operational endpoints under `/memory`:
    - `POST /memory/provision`
    - `GET /memory/health`
    - `GET /memory/config`
    - `GET /memory/metrics`
    - `POST /memory/search`
    - `POST /memory/write-debug`

## Configuration

- `backend/config.py`
  - `Settings.from_env()` loads and validates env vars.
  - Enforces required `MOORCHEH_API_KEY`.
  - Enforces `EMBEDDING_API_KEY` when provider is not `mock`.
  - Enforces numeric bounds for vector dim, conflict threshold, etc.
  - Provides safe redacted config for diagnostics.

## Moorcheh + embeddings

- `backend/memory/moorcheh_client.py`
  - Wrapper around the official `moorcheh-sdk` Python SDK.
  - Implements Moorcheh operations with automatic retry/error handling via SDK:
    - list namespaces
    - create vector namespace
    - ensure vector namespace exists and dim matches
    - upload vectors
    - vector search
    - answer generation endpoint wrapper
    - health check
  - SDK handles authentication, retry logic, and all HTTP details transparently.

- `backend/memory/embedding_provider.py`
  - `MockEmbeddingProvider`: deterministic vectors for tests/dev.
  - `OpenAICompatibleEmbeddingProvider`: calls embeddings endpoint via HTTP.
  - Enforces vector dimension consistency.
  - `build_embedding_provider(settings)` factory.

- `backend/memory/moorcheh_store.py`
  - High-level facade that joins embedder + Moorcheh client.
  - Methods:
    - `provision_namespace()`
    - `health_check()`
    - `write_record()`, `write_records()`
    - `search_context(query_text, top_k, threshold, metadata_filters)`
  - Tracks telemetry on write/search/provision/health/errors.

- `backend/memory/telemetry.py`
  - In-memory counters + latency snapshots:
    - write/search counts
    - vector/result counts
    - avg write/search ms
    - last error

## Memory schema and workflow helpers

- `backend/memory/schemas.py`
  - Canonical `ContextRecord`.
  - `RecordType`, `WorkflowStage` enums.
  - Deterministic record IDs: `wf:{workflow_id}:run:{run_id}:evt:{event_seq}:{record_type}`.
  - `to_vector_payload()` builds final Moorcheh vector metadata payload.

- `backend/memory/context_writer.py`
  - `WorkflowContextWriter` writes normalized events.
  - Supports explicit or auto event sequence by run.
  - Convenience methods:
    - `write_goal()`
    - `write_plan()`
    - `write_task_update()`
    - `write_conflict_assessment()`

- `backend/memory/context_reader.py`
  - `WorkflowContextReader` prefetches context for:
    - planner (`fetch_for_planner`)
    - coordinator (`fetch_for_coordinator`)
  - Generates natural language retrieval query, calls vector search, summarizes context, and formats prompt-ready text.

- `backend/memory/conflict_context.py`
  - `ConflictCompensator` analyzes retrieved memory + task drafts.
  - Detects overlap/hot-file signals.
  - Adjusts dependencies, priority, and parallelizable flags to reduce collisions.
  - Returns `CompensationDecision` with `adjusted_tasks`, `conflict_signals`, and summary.

## Async-agent context contract

- `backend/agents/context_contract.py`
  - `AsyncAgentContext` schema for payload passed into async agents.
  - `build_async_agent_context(...)`
  - `parse_async_agent_context(payload)` validation/parser.

## Prize-track harness

- `backend/evaluation/prize_track_harness.py`
  - Simulates baseline vs memory-aware conflict compensation.
  - Outputs overlap reduction and signal metrics.


## Tests Added

- `tests/test_config.py`
  - Validates config failures for missing required keys.

- `tests/test_schemas.py`
  - Validates deterministic IDs and vector payload shape.

- `tests/test_conflict_compensation.py`
  - Verifies overlap serialization + non-parallelization under conflict pressure.

- `tests/test_memory_loop.py`
  - End-to-end write/read loop using a fake Moorcheh client.

- `tests/test_async_context_contract.py`
  - Validates context payload roundtrip.

- `pytest.ini`
  - `pythonpath = .`, `testpaths = tests`

- `requirements.txt`
  - `fastapi`, `pydantic`, `pytest`, `uvicorn`, `moorcheh-sdk`


## Data Model Stored in Moorcheh (Vector Namespace)

Each context event is uploaded as one vector record with metadata, including:

- `id`
- `vector`
- `source`
- `index`
- `raw_text`
- `workflow_id`
- `run_id`
- `agent_id`
- `record_type`
- `stage`
- `status`
- `task_id`
- `file_paths`
- `depends_on`
- `conflict_score`
- `timestamp`
- `embedding_model`
- `embedding_dimension`
- `schema_version`


## Environment Variables (Real Deployment)

Required for real Moorcheh + real embeddings:

```bash
export MOORCHEH_API_KEY="mc_..."
export MOORCHEH_BASE_URL="https://api.moorcheh.ai/v1"   # optional, default set

export MOORCHEH_VECTOR_NAMESPACE="workflow-context-vectors"  # optional default exists
export MOORCHEH_VECTOR_DIMENSION="1536"                      # must match embedding output

export EMBEDDING_PROVIDER="openai"                           # openai or mock
export EMBEDDING_MODEL="text-embedding-3-small"
export EMBEDDING_API_KEY="sk-..."

# optional override, expects full embeddings endpoint in current code:
export EMBEDDING_BASE_URL="https://api.openai.com/v1/embeddings"

export EMBEDDING_BATCH_SIZE="32"
export CONTEXT_RETRIEVAL_TOP_K="12"
export CONFLICT_THRESHOLD="0.35"
export MAX_CONTEXT_WINDOW="40"
```

Notes:

- If `EMBEDDING_PROVIDER` is not `mock`, `EMBEDDING_API_KEY` is required.
- `MOORCHEH_VECTOR_DIMENSION` **must** equal your embedding model output dimension.
- Keep keys in env/secrets, never in source code.


## How To Use It With a Real Moorcheh DB

### Prerequisites

- Moorcheh account and API key from https://console.moorcheh.ai
- Python 3.8+
- `.venv` or Python environment

### 1) Install dependencies

```bash
python -m pip install -r requirements.txt
```

This installs:
- `fastapi`, `uvicorn` for the API server
- `moorcheh-sdk` for Moorcheh API interactions (automatically handles auth and retries)
- `pydantic` for config validation
- `pytest` for tests

### 2) Export environment variables

Create or update your `.env` file at the repo root:

```bash
export MOORCHEH_API_KEY="mc_<your-key-here>"
export MOORCHEH_BASE_URL="https://api.moorcheh.ai/v1"

export MOORCHEH_VECTOR_NAMESPACE="workflow-context-vectors"
export MOORCHEH_VECTOR_DIMENSION="1536"

export EMBEDDING_PROVIDER="openai"  # or "mock" for tests
export EMBEDDING_API_KEY="sk_<your-key-here>"
export EMBEDDING_MODEL="text-embedding-3-small"
export EMBEDDING_BASE_URL="https://api.openai.com/v1/embeddings"
```

Then source it:

```bash
set -o allexport && source ./.env && set +o allexport
```

### 3) Start the backend API

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

## 4) Provision (or verify) vector namespace

```bash
curl -X POST http://127.0.0.1:8000/memory/provision
```

Expected behavior:

- Creates namespace if missing (uses Moorcheh SDK).
- Returns `exists` if already present.
- Throws error if existing namespace dimension mismatches config.

### 5) Check health/config/telemetry

```bash
curl http://127.0.0.1:8000/memory/health
curl http://127.0.0.1:8000/memory/config
curl http://127.0.0.1:8000/memory/metrics
```

### 6) Write a sample context event

```bash
curl -X POST http://127.0.0.1:8000/memory/write-debug \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "wf-demo",
    "run_id": "run-1",
    "record_type": "plan",
    "stage": "planning",
    "status": "done",
    "raw_text": "Planner approved split across auth and billing.",
    "agent_id": "planner",
    "event_seq": 0,
    "file_paths": ["src/auth.py", "src/billing.py"]
  }'
```

### 7) Search context semantically

```bash
curl -X POST http://127.0.0.1:8000/memory/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "previous planning decisions for auth files",
    "top_k": 10,
    "threshold": 0.2,
    "metadata_filters": {
      "workflow_id": "wf-demo"
    }
  }'
```

This query is automatically embedded and searched against stored vectors using the Moorcheh SDK.


## Programmatic Usage in Your Orchestrator

Use these classes directly inside planning/coordinator/coder pipelines:

```python
from backend.memory.moorcheh_store import MoorchehVectorStore
from backend.memory.context_writer import WorkflowContextWriter
from backend.memory.context_reader import WorkflowContextReader
from backend.memory.conflict_context import ConflictCompensator, TaskDraft
from backend.memory.schemas import RecordType, WorkflowStage

store = MoorchehVectorStore()
store.provision_namespace()

writer = WorkflowContextWriter(store)
reader = WorkflowContextReader(store)
compensator = ConflictCompensator()

# Write event
writer.write_event(
    workflow_id="wf-123",
    run_id="run-7",
    record_type=RecordType.PLAN,
    stage=WorkflowStage.PLANNING,
    status="done",
    raw_text="Initial plan approved with three coder tasks.",
    agent_id="planner",
)

# Prefetch context for planner
bundle = reader.fetch_for_planner(
    workflow_id="wf-123",
    goal_text="Implement conflict-aware parallel coding.",
    planned_files=["src/auth.py", "src/merge.py"]
)
prompt_context = reader.format_for_prompt(bundle)

# Compensate tasks
tasks = [
    TaskDraft(task_id="t1", agent_id="a1", file_paths=["src/auth.py"]),
    TaskDraft(task_id="t2", agent_id="a2", file_paths=["src/auth.py", "src/ui.py"]),
]
decision = compensator.compensate(tasks=tasks, context_records=bundle.records)
```


## Async Agent Context Contract

Use `backend/agents/context_contract.py` to pass a normalized startup payload:

- objective/stage/workflow identity
- retrieved memory records + summary
- assigned tasks
- conflict signals
- constraints

This is intended to ensure async agents can resume with shared memory context and lower conflict risk.


## Prize-Track Benchmark Harness

Run:

```bash
python -m backend.evaluation.prize_track_harness
```

This prints a baseline vs memory-aware comparison and includes overlap reduction metrics.


## Testing & Validation

### Run unit and integration tests

```bash
python -m pytest -q
```

All tests pass using:
- Mock embedding provider (deterministic vectors)
- Fake Moorcheh client for local tests
- Real Moorcheh SDK for live integration

### Live integration test (with real API key)

If `MOORCHEH_API_KEY` is set in your environment, the implementation uses the official Moorcheh SDK to:
1. List existing namespaces
2. Create or verify vector namespace with correct dimension
3. Upload vectors with metadata
4. Search and retrieve results
5. Return status and telemetry

Example from 2026-03-14 live test:
```
✓ Upload: 3 vectors added
✓ Search: 5 hits returned
✓ Metadata: workflow_id, record_type, agent_id preserved
```

Tests pass for config, schema, conflict compensation, memory loop, and async context contract (7 passed).


## Implementation Details

### Why Moorcheh SDK?

The implementation switched from custom REST client to the official `moorcheh-sdk` for:
- **Automatic auth**: SDK handles `x-api-key` header and future auth schemes
- **Retry logic**: Built-in exponential backoff for transient failures
- **Type safety**: Official SDK response types and validation
- **Maintainability**: Follows Moorcheh's official patterns and updates

### Architecture

```
┌─ FastAPI routes ─────────┐
│ /memory/provision         │
│ /memory/write-debug       │
│ /memory/search            │
│ /memory/health            │
└──────────┬────────────────┘
           │
┌──────────▼─────────────────────────────────────────┐
│ MoorchehVectorStore (facade)                       │
│ - embedding provider (mock | openai)               │
│ - moorcheh client (SDK wrapper)                    │
│ - telemetry                                        │
└──────────┬─────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│ moorcheh_client.py (SDK wrapper)                │
│ - list_namespaces()                             │
│ - upload_vectors()                              │
│ - search_vectors()                              │
│ - generate_answer()                             │
│ - ensure_vector_namespace()                     │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│ moorcheh-sdk (Official Python SDK)              │
│ - client.namespaces.list()                      │
│ - client.vectors.upload()                       │
│ - client.search()                               │
│ - Automatic auth, retries, error handling       │
└──────────┬──────────────────────────────────────┘
           │
           └──→ Moorcheh API (https://api.moorcheh.ai/v1)
```

### Known Gaps / Next Wiring Step

The current code provides memory infrastructure and diagnostics. To make it fully live in production orchestration, wire:

- planner/coordinator/coder/merge/qa state transitions to `WorkflowContextWriter`
- planner/coordinator startup context fetch to `WorkflowContextReader`
- task assignment rebalancing to `ConflictCompensator`
- async payload handoff to `build_async_agent_context(...)`

Once those calls are connected to your runtime state machine, the Moorcheh memory loop is fully operational.

