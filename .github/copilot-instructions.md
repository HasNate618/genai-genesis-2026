# Copilot Instructions for AgenticArmy

## Project Overview

**AgenticArmy** is a multi-agent orchestration system that generates code through intelligent parallel execution. Agents (planner, coordinator, coders, QA) communicate through a shared semantic memory layer powered by **Moorcheh** (vector database).

**Core problem solved:** Multi-agent systems without shared memory create merge conflicts and wasted compute. AgenticArmy uses semantic memory to help agents anticipate conflicts, sequence tasks intelligently, and learn from previous failures.

**Current state:** MVP complete with Moorcheh SDK integration, `/api/v1` contract endpoints, state machine orchestration, HITL review gates, and 11 passing tests. Ready for real agent integration (Railtracks) and VS Code extension integration.

---

## Build, Test, and Lint

### Prerequisites
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run all tests
```bash
pytest tests/ -v
```

### Run a single test file
```bash
pytest tests/test_api_v1_contract.py -v
```

### Run a single test
```bash
pytest tests/test_api_v1_contract.py::test_health_contract_shape -v
```

### Start the backend
```bash
# Terminal 1: Set up env (if not already set)
set -o allexport && source .env && set +o allexport

# Terminal 2: Run server
uvicorn backend.main:app --reload --port 8000

# Verify with curl
curl -X GET http://localhost:8000/api/v1/health
```

### Configuration
- `.env` required at root (not in repo; contains `MOORCHEH_API_KEY`, `EMBEDDING_API_KEY` if using OpenAI)
- `EMBEDDING_PROVIDER=mock` (default) runs without external embeddings
- `EMBEDDING_PROVIDER=openai` requires `EMBEDDING_API_KEY`
- Config loaded via `backend.config.Settings.from_env()` with support for per-job key overrides

---

## Architecture

### High-Level Flow

```
User Goal → Planner → Human Review (HITL Gate 1) → Coordinator → Coders (Parallel) → 
QA Verification → Human Review (HITL Gate 2) → Done
```

Each phase writes to/reads from Moorcheh for context awareness and conflict detection.

### Core Components

**1. API Contract Layer** (`backend/api/v1.py`)
- `GET /health` — Server liveness check
- `POST /jobs` — Create job with goal
- `GET /jobs/{job_id}/status` — Poll for job progress
- `POST /jobs/{job_id}/plan/review` — Approve/reject plan (unblocks HITL gate 1)
- `POST /jobs/{job_id}/result/review` — Approve/reject final result (unblocks HITL gate 2)
- Response shape: `{ job_id, status, logs[], agentStates{} }`
- All responses include metadata for UI state rendering

**2. Job Runtime State Machine** (`backend/core/job_runtime.py`)
- In-memory job registry; keyed by UUID
- Strict state transitions: `initializing → planning → awaiting_plan_approval → coordinating → coding → verifying → review_ready → done|failed`
- Each state runs a background phase (async mocks currently; real agents plug in here)
- HITL gates via `asyncio.Event` objects (`plan_approved`, `result_approved`)
- Background task executor ticks at configurable interval (default 0.05s)

**3. Moorcheh Memory Layer** (`backend/memory/`)
- **`moorcheh_store.py`** — Facade; handles namespace provisioning, vector upload, semantic search
- **`moorcheh_client.py`** — Official SDK wrapper (auth, retries, namespace ops)
- **`context_reader.py`** — Retrieve relevant historical context for planner/coordinator
- **`context_writer.py`** — Record goals, plans, tasks, failures, conflicts into Moorcheh
- **`conflict_context.py`** — Analyze past conflicts, suggest task rebalancing
- **`embedding_provider.py`** — OpenAI or mock embeddings (configurable)
- **`schemas.py`** — Record types (goal, plan, task, failure, conflict), deterministic ID generation

**4. VS Code Extension** (`vscode-extension/`)
- Polls `/api/v1/jobs/{job_id}/status` every 2 seconds
- Renders agent state, task progress, logs
- Triggers human review via `/plan/review` and `/result/review` endpoints
- Note: Extension integration not yet tested; API contract assumed correct per `docs/backend_architecture_reference.md`

### Data Flow: Planning Phase Example

1. User submits goal via UI → `POST /api/v1/jobs`
2. Backend creates job, status = `planning`
3. Job runtime's background task calls planner phase
4. Planner reads Moorcheh: `ContextReader.fetch_for_planner()` retrieves previous plans, failures
5. Planner generates new plan, writes to Moorcheh: `ContextWriter.write_plan()`
6. Status changes to `awaiting_plan_approval`; blocks on `plan_approved` Event
7. UI shows human review prompt
8. Human POSTs to `/plan/review?approved=true` → unsets Event → phase unblocks
9. Next phase (coordination) starts

### Memory Integration Points

| Phase | Operation | Module |
| --- | --- | --- |
| **Planning** | Read prior attempts, write approved plan | `context_reader.fetch_for_planner()`, `context_writer.write_plan()` |
| **Coordination** | Read context, detect overlaps, suggest rebalancing | `context_reader.fetch_for_coordinator()`, `conflict_context.ConflictCompensator` |
| **Coding** | Record task progress, failures | `context_writer.write_task_update()` |
| **Verification** | Record test results, QA findings | `context_writer.write_event()` |

---

## Key Conventions

### Record IDs (Deterministic & Idempotent)
```python
# Format: wf:{workflow_id}:run:{run_id}:evt:{sequence}:{type}
# Same input → same ID → Moorcheh upserts (no duplicates)
from backend.memory.schemas import ContextRecord
record_id = ContextRecord.deterministic_id(
    workflow_id="user-goal-123",
    run_id="exec-456",
    sequence=1,
    record_type="plan"
)
# Result: "wf:user-goal-123:run:exec-456:evt:1:plan"
```

### Response Shape (All Endpoints)
```python
# All POST/GET responses follow this shape
{
    "job_id": "uuid-string",
    "status": "planning|awaiting_plan_approval|coordinating|...",
    "logs": ["log1", "log2", ...],
    "agentStates": {
        "planner": {"state": "...", "progress": 0-100},
        "coordinator": {...},
        ...
    },
    "data": {...}  # Endpoint-specific payload
}
```

### Job State Storage (In-Memory)
```python
# Internal job object shape (keys to remember)
job = {
    "job_id": str,
    "goal": str,
    "status": str,  # Exact strings: initializing, planning, awaiting_plan_approval, ...
    "logs": [str],  # Append-only
    "agentStates": dict,
    "plan_approved": asyncio.Event(),  # HITL gate 1
    "result_approved": asyncio.Event(),  # HITL gate 2
    "moorcheh_key": None,  # Never stored; only used at init time
    "coder_count": int,
    "created_at": float,
    "updated_at": float,
}
```

### Config & Per-Job Overrides
```python
from backend.config import Settings

# Load with defaults
settings = Settings.from_env()

# Load with per-job overrides (e.g., user-supplied Moorcheh key)
settings = Settings.from_env(moorcheh_api_key=request.moorcheh_key)
# Result: temporary Settings object; key never persisted to job state
```

### Moorcheh Namespaces
- **`workflow-context-vectors`** — Main namespace for all job context (plans, tasks, failures)
- Dimension: 1536 (OpenAI) or configurable via mock
- Each record stored as: vector + metadata (workflow_id, record_type, raw_text, timestamp)
- Deterministic IDs prevent duplicates on re-write

### HITL Gate Pattern
```python
# In job runtime background loop:
await job["plan_approved"].wait()  # Blocks until human review

# When human POSTs to /plan/review?approved=true:
job["plan_approved"].set()  # Unblocks the wait()
```

### Testing Patterns
- All tests use `mock` embedding provider (no external API calls)
- Contract tests in `tests/test_api_v1_contract.py` validate endpoint shapes and state transitions
- Memory loop tests in `tests/test_memory_loop.py` validate read/write round-trips
- Use `pytest -v` for verbose output; check `test_*.py` files for examples

---

## Files to Know

| File | Purpose |
| --- | --- |
| `backend/main.py` | FastAPI app, lifespan, CORS middleware, router registration |
| `backend/api/v1.py` | `/api/v1` contract endpoints (health, jobs, reviews, status) |
| `backend/api/memory_routes.py` | `/memory/*` debug routes (deprecated; for testing only) |
| `backend/core/job_runtime.py` | State machine, background task loop, HITL gates |
| `backend/memory/moorcheh_store.py` | Vector store facade (namespace ops, search, upload) |
| `backend/memory/context_reader.py` | Query Moorcheh for planner/coordinator context |
| `backend/memory/context_writer.py` | Write goals, plans, tasks, failures to Moorcheh |
| `backend/memory/conflict_context.py` | Conflict analysis; suggest task rebalancing |
| `backend/config.py` | Settings loader; env var handling; per-job overrides |
| `backend/memory/schemas.py` | Record types, deterministic ID generation |
| `tests/test_api_v1_contract.py` | Contract & state machine tests |
| `tests/test_memory_loop.py` | Moorcheh read/write round-trip tests |
| `docs/backend_architecture_reference.md` | API contract reference (source of truth for endpoints) |
| `docs/Moorcheh.md` | Integration guide, SDK usage, live test results |

---

## Common Patterns

### Adding a New Endpoint
1. Define request/response models in `backend/api/v1.py`
2. Implement endpoint handler in same file
3. Register with FastAPI app in `backend/main.py` (already done for `/api/v1` router)
4. Add test in `tests/test_api_v1_contract.py`
5. Verify response shape matches architecture reference

### Wiring a New Phase
1. Add phase to job runtime's background loop in `backend/core/job_runtime.py`
2. Call `ContextReader` methods to fetch relevant context
3. Call `ContextWriter` methods to record decisions/outcomes
4. Update status string to exact value from architecture reference
5. Add HITL gate with `asyncio.Event` if human approval needed

### Writing to Moorcheh
```python
from backend.memory.context_writer import WorkflowContextWriter

writer = WorkflowContextWriter(settings)
writer.write_plan(
    workflow_id="job-123",
    run_id="exec-456",
    plan_text="Refactor auth.py then database.py",
    approved_by="human-reviewer"
)
# Internally:
# 1. Generate deterministic record ID
# 2. Embed plan_text via embedding provider
# 3. Upload vector to moorcheh-store with metadata
```

### Reading from Moorcheh
```python
from backend.memory.context_reader import WorkflowContextReader

reader = WorkflowContextReader(settings)
context = reader.fetch_for_planner(
    workflow_id="job-123",
    limit=5  # Top 5 similar past plans
)
# Result: [{"text": "...", "similarity": 0.95, "metadata": {...}}, ...]
```

---

## Debugging Tips

### Check Moorcheh namespaces
```bash
# Via backend debug endpoint (if enabled)
curl http://localhost:8000/memory/namespaces

# Result shows 3 main namespaces and record counts
```

### Run a single test with output
```bash
pytest tests/test_memory_loop.py -v -s
```

### Enable verbose logging
Set `DEBUG=1` in `.env` (if logging is implemented; currently minimal)

### Test without Moorcheh API key
Use `EMBEDDING_PROVIDER=mock` (default). Backend works locally without real Moorcheh credentials.

### Simulate a full job lifecycle
```bash
# 1. Create job
JOB_ID=$(curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"goal": "...", "coder_count": 2, "moorcheh_key": "mc_test"}' | jq -r '.job_id')

# 2. Poll status (repeating)
curl http://localhost:8000/api/v1/jobs/$JOB_ID/status

# 3. Once status = awaiting_plan_approval, approve plan
curl -X POST http://localhost:8000/api/v1/jobs/$JOB_ID/plan/review \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'

# 4. Continue polling until review_ready
# 5. Review and approve result
curl -X POST http://localhost:8000/api/v1/jobs/$JOB_ID/result/review \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'

# 6. Job should transition to done
```

---

## Important Notes

- **No real agents yet.** Phases currently use `asyncio.sleep()` mocks. Phase 2 will wire Railtracks agent implementations.
- **Extension integration not tested.** API contract assumed correct; real integration testing pending.
- **In-memory only.** Jobs stored in RAM; lost on server restart. Add PostgreSQL for persistence if needed.
- **Mock embeddings by default.** Tests use deterministic mock embeddings; OpenAI optional via config.
- **Moorcheh key handling.** Pass `moorcheh_key` in request; never stored in job state or logs.
- **HITL gates block the background task.** Plan/result review endpoints unblock by setting Event objects.

---

## References

- **API Contract:** `docs/backend_architecture_reference.md` (source of truth for endpoint shapes)
- **Moorcheh Integration:** `docs/Moorcheh.md` (how to use with real Moorcheh DB)
- **Beginner Guide:** `docs/Moorcheh_Explained_For_Everyone.md` (non-technical overview)
- **DevPost:** `devpost.md` (project summary and wins)
- **Railtracks:** https://github.com/RailtownAI/railtracks/ (agent orchestration framework)
- **Moorcheh SDK:** https://github.com/moorcheh-ai/moorcheh-python-sdk (official Python SDK)
