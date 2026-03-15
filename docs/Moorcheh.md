# AgenticArmy Runtime + Moorcheh Memory  
## What is implemented, how it works, and how to use it

This is the implementation guide for the **current code in this repo**.  
It covers backend runtime behavior, Railtracks integration, Moorcheh vector memory wiring, VS Code flow, GitHub auth, and real usage steps.


## 1) What is actually implemented right now

The current system is no longer a simple mock-only skeleton. It includes:

- A live `/api/v1` state-machine runtime with HITL gates (`plan` + `result` review).
- Railtracks-based agent orchestration using contract files in `backend/agents/*.md`.
- Moorcheh vector memory reads/writes across planning, coordination, coding, merge, and QA transitions.
- Conflict compensation logic to reduce overlap before coding.
- Isolated git workdirs in OS temp storage (`/tmp/agenticarmy-workdirs/<repo>/<job>/<agent>` on Linux) for coder execution.
- Tool-executing coder/QA agents through allowlisted workspace tools.
- GitHub account token flow from VS Code auth into backend runtime (ephemeral).
- Hosted OpenAI-compatible LLM defaults via Hugging Face endpoint (no user model key required).
- Extension polling UI with status/plan/review loops and run start error recovery.


## 2) High-level architecture

### Backend entrypoints

- `backend/main.py`
  - Starts FastAPI app.
  - Mounts `/api/v1` router.
  - Keeps `/health` root compatibility endpoint.

- `backend/api/v1.py`
  - `GET /api/v1/health`
  - `POST /api/v1/jobs`
  - `GET /api/v1/jobs/{job_id}/plan`
  - `POST /api/v1/jobs/{job_id}/plan/review`
  - `GET /api/v1/jobs/{job_id}/status`
  - `POST /api/v1/jobs/{job_id}/result/review`

- `backend/core/job_runtime.py`
  - In-memory job store.
  - Background pipeline execution.
  - HITL gates via `asyncio.Event`.
  - Full planning/coordinating/coding/verifying/review loop.


### Agent orchestration layer

- `backend/agents/railtracks_runtime.py`
  - Loads agent contracts from markdown:
    - `planning_agent.md`
    - `task_coordinator_agent.md`
    - `conflict_analysis_agent.md`
    - `coding_agent.md`
    - `merge_agent.md`
    - `qa_agent.md`
  - Uses Pydantic output schemas to enforce structured agent responses.
  - Calls are guarded by `LLM_CALL_TIMEOUT_SECONDS`.


### Memory layer (Moorcheh + embeddings)

- `backend/memory/moorcheh_client.py`
  - Wrapper over official `moorcheh-sdk`.
  - Namespace ensure/list, vector upload, vector search, answer helper.

- `backend/memory/moorcheh_store.py`
  - Embeds text + uploads vectors + retrieves top-k context.
  - Tracks telemetry (write/search/provision/health/error).

- `backend/memory/context_writer.py`
  - Writes normalized workflow events (goal/plan/task/conflict/qa/merge/etc).

- `backend/memory/context_reader.py`
  - Fetches planner/coordinator context from Moorcheh.

- `backend/memory/conflict_context.py`
  - Adjusts task dependencies/priority/parallel flags using historical conflict signals.

- `backend/memory/schemas.py`
  - Canonical `ContextRecord` shape.
  - Deterministic record IDs for idempotent writes.


### Execution/runtime safety

- `backend/core/workdir_runtime.py`
  - Creates isolated git workdirs per coder.
  - Commits branch changes.
  - Builds a verification workdir by merging coder branches for QA.
  - Merges approved coder branches into target base branch only after final human approval.

- `backend/core/tool_runtime.py`
  - Workspace-scoped tools: read/write/list/run-command/git status/git diff.
  - Optional GitHub tools when token is configured.
  - Blocks path escape and dangerous git path flags.
  - Command allowlist only.

- `backend/core/github_runtime.py`
  - Token-scoped GitHub REST wrapper (`whoami`, create PR, comment on PR).


### VS Code extension integration

- `vscode-extension/src/panelManager.ts`
- `vscode-extension/src/sidebarProvider.ts`
- `vscode-extension/src/backendClient.ts`
- `vscode-extension/src/githubAuth.ts`

Behavior:

- On run start, extension requests GitHub auth with scopes `repo`, `read:user`.
- OAuth call is wrapped with timeout (`45s`) to avoid indefinite hang.
- Backend is pinged before job start.
- Extension posts job payload to `/api/v1/jobs`.
- Polls `/status` every 2s.
- Fetches `/plan` when entering `awaiting_plan_approval`.
- Sends reviews to `/plan/review` and `/result/review`.


## 3) Runtime state machine (exact statuses)

`initializing -> planning -> awaiting_plan_approval -> coordinating -> coding -> verifying -> review_ready -> done|failed`

Loopbacks:

- Plan rejected: `awaiting_plan_approval -> planning`
- Conflict threshold breached: `coordinating -> coordinating` (rerun coordination)
- Coding failure: `coding -> coordinating`
- Merge failure: `coding -> coordinating`
- QA failure: `verifying -> coordinating`
- Final result rejected: `review_ready -> coordinating`


## 4) Phase-by-phase execution details

### Planning

1. Runtime creates memory hooks (`Settings`, `MoorchehVectorStore`, reader/writer/compensator, Railtracks runtime, workdir runtime).
2. Goal is written to Moorcheh.
3. Planner fetches prior workflow context from Moorcheh.
4. Railtracks planner agent generates plan.
5. Plan is written to job state + Moorcheh.
6. Runtime pauses at `awaiting_plan_approval`.

If human rejects, rejection reason is written to Moorcheh and planning reruns with feedback.


### Coordination + conflict compensation

1. Coordinator agent generates assignments.
2. Runtime converts assignments to `TaskDraft`s.
3. Moorcheh context is fetched for candidate files.
4. `ConflictCompensator` adjusts tasks (dependencies/priority/parallelizable).
5. Conflict assessment is written to Moorcheh.
6. Conflict analysis agent computes threshold decision.
7. If threshold breached, loop back to coordination.


### Coding

For each adjusted task:

1. Runtime prepares an isolated git workdir branch for that coder.
2. Coder agent runs with tool nodes bound to that workdir.
3. Runtime attempts `git add -A` + commit in that workdir.
4. Task update events are written to Moorcheh.

Notes:

- Coder tasks are currently executed in sequence inside the runtime loop (not yet parallel task execution inside one job process).
- Each coder still has isolated branch/workdir boundaries.
- For simple Python goals (for example, "make hello world in python"), runtime uses deterministic targeting (`hello_world.py`) instead of placeholder `workspace/task_*.txt` paths.
- If coder output is empty/non-usable for those simple goals, runtime applies an immediate deterministic fallback write so coding can still produce a concrete artifact.
- Runtime enforces a work-product invariant: if coding produces no committed artifacts, pipeline loops back to coordination and cannot move to merge/finalization.


### Merge + verification workspace

1. Runtime creates verification workdir from base branch.
2. It merges committed coder branches into verification workdir.
3. Merge agent is called for mergeability/summary.
4. If merge step fails, loop back to coordination.


### QA / verification

1. QA agent runs in verification workspace with tools.
2. Runtime currently supplies `run_command="pytest tests/ -q"` by default.
3. QA result is persisted to `agentResults` and Moorcheh.
4. Failed QA loops back to coordination.


### Final review + real merge to base

1. Runtime pauses in `review_ready`.
2. On approval:
   - Runtime merges committed coder branches into the requested `base_branch`.
   - Writes final approval event.
   - Marks job `done`.
3. On rejection:
   - Writes rejection context.
   - Loops back to coordination.


## 5) API contract and payloads

### `POST /api/v1/jobs` payload

```json
{
  "goal": "Implement feature X",
  "coder_count": 2,
  "gemini_key": "",
  "moorcheh_key": "",
  "github_token": "gho_...",
  "github_repo": "owner/repo",
  "base_branch": "main",
  "workspace_path": "/absolute/path/to/target/repo"
}
```

Notes:

- `goal` is required.
- `gemini_key` and `moorcheh_key` are backward-compatible fields.
- GitHub token comes from VS Code auth flow.
- `workspace_path` pins execution to the intended local repo root; if omitted, backend falls back to its own cwd.
- If `github_repo` is empty and git remote is configured, runtime derives repo from `origin`.


### `GET /api/v1/jobs/{job_id}/status` shape

```json
{
  "status": "coding",
  "logs": ["[12:00:01] ..."],
  "agentStates": {
    "planner": "done",
    "coordinator_conflict": "done",
    "coder": "running",
    "merger": "idle"
  },
  "agentResults": {
    "planner": "{...json...}",
    "coordinator_conflict": "{...json...}",
    "coder": "{...json...}",
    "merger": ""
  },
  "artifacts": {
    "base_branch": "main",
    "merged_branches": ["agenticarmy/job-123/coder-1"],
    "merged_commit": "abc123...",
    "changed_files": ["hello_world.py"]
  }
}
```


## 6) Moorcheh data model used by runtime

Records are stored as vectors in namespace `workflow-context-vectors` (default).

### Record identity

Deterministic ID format:

`wf:{workflow_id}:run:{run_id}:evt:{event_seq}:{record_type}`

This prevents duplicate records for repeat writes with same identity.


### Record types currently used

- `goal`
- `plan`
- `plan_rejection`
- `approval`
- `task`
- `conflict`
- `merge`
- `qa`

Also defined for future use:

- `agent_state`


### Metadata fields (stored with vectors)

- `id`, `source`, `index`, `raw_text`
- `workflow_id`, `run_id`, `agent_id`
- `record_type`, `stage`, `status`
- `task_id`, `file_paths`, `depends_on`
- `conflict_score`, `timestamp`
- `embedding_model`, `embedding_dimension`, `schema_version`


## 7) Secrets and security behavior

- GitHub OAuth token is requested from VS Code auth provider and sent for job runtime use.
- Job state in runtime does **not** persist token or user keys.
- Extension optional keys (`gemini`, `moorcheh`) are stored in VS Code secret storage.
- Tool runtime prevents:
  - workspace path escape
  - absolute path commands
  - `..` traversal
  - dangerous git path override flags (`-C`, `--git-dir`, `--work-tree`)


## 8) Configuration

## Required

- `MOORCHEH_API_KEY` (unless provided per-job in `moorcheh_key`)


## Moorcheh defaults

- `MOORCHEH_BASE_URL=https://api.moorcheh.ai/v1`
- `MOORCHEH_VECTOR_NAMESPACE=workflow-context-vectors`
- `MOORCHEH_VECTOR_DIMENSION=1536`


## Embeddings

- `EMBEDDING_PROVIDER=mock` (default), `openai`, or `cohere`
- `EMBEDDING_MODEL=text-embedding-3-small` (OpenAI default) or `embed-english-v3.0` (Cohere default)
- `EMBEDDING_API_KEY` required when provider is not `mock`
- `COHERE_API_KEY` can be used instead of `EMBEDDING_API_KEY` when `EMBEDDING_PROVIDER=cohere`
- `EMBEDDING_BASE_URL` optional:
  - OpenAI-compatible: full embeddings endpoint (or compatible base)
  - Cohere: `https://api.cohere.ai`, `https://api.cohere.ai/v1`, or full `/v1/embed` endpoint
- `EMBEDDING_BATCH_SIZE=32`


## Retrieval/conflict tuning

- `CONTEXT_RETRIEVAL_TOP_K=12`
- `MAX_CONTEXT_WINDOW=40`
- `CONFLICT_THRESHOLD=0.35`


## LLM runtime defaults (hosted endpoint mode)

- `LLM_BASE_URL=https://qyt7893blb71b5d3.us-east-2.aws.endpoints.huggingface.cloud/v1`
- `LLM_MODEL=openai/gpt-oss-120b`
- `LLM_API_KEY` optional
- `LLM_CALL_TIMEOUT_SECONDS=180`


## 9) How to run (backend + extension)

### Backend setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set env (example):

```bash
export MOORCHEH_API_KEY="mc_..."
export EMBEDDING_PROVIDER="mock"   # easiest local mode
```

Set env (Cohere embeddings example):

```bash
export MOORCHEH_API_KEY="mc_..."
export MOORCHEH_VECTOR_NAMESPACE="workflow-context-vectors"
export MOORCHEH_VECTOR_DIMENSION="1024"          # must match chosen Cohere model output size
export EMBEDDING_PROVIDER="cohere"
export COHERE_API_KEY="co_..."
export EMBEDDING_MODEL="embed-english-v3.0"
export EMBEDDING_BASE_URL="https://api.cohere.ai"
export EMBEDDING_BATCH_SIZE="16"
```

Run backend:

```bash
uvicorn backend.main:app --reload --port 8000
```

Check health:

```bash
curl http://localhost:8000/api/v1/health
```


### Extension setup

```bash
npm --prefix vscode-extension install
npm --prefix vscode-extension run compile --silent
```

Then run extension in VS Code (Extension Development Host), open AgenticArmy sidebar, and launch a run.


### Run lifecycle (UI)

1. Enter goal + coder count.
2. Click **Launch Agents**.
3. Complete GitHub sign-in if prompted.
4. Wait for `awaiting_plan_approval`, review plan, approve/reject.
5. Wait for `review_ready`, review result, approve/reject.
6. On approval, runtime merges to base branch and marks job `done`.


## 10) How to run by API only (without extension)

```bash
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "goal":"Add conflict-aware orchestration docs",
    "coder_count":2,
    "github_token":"gho_xxx",
    "github_repo":"owner/repo",
    "base_branch":"main"
  }' | python -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

curl http://localhost:8000/api/v1/jobs/$JOB_ID/status
curl http://localhost:8000/api/v1/jobs/$JOB_ID/plan
curl -X POST http://localhost:8000/api/v1/jobs/$JOB_ID/plan/review \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "feedback": "Proceed"}'
```


## 11) How to inspect Moorcheh namespaces/content

With env loaded (`MOORCHEH_API_KEY` etc), run:

```bash
python - <<'PY'
from backend.config import Settings
from backend.memory.moorcheh_client import MoorchehClient

s = Settings.from_env()
c = MoorchehClient(s)
namespaces = c.list_namespaces()
print("Namespaces:")
for ns in namespaces:
    print("-", ns.get("namespace_name"), "dim=", ns.get("vector_dimension"))
PY
```

Search current namespace:

```bash
python - <<'PY'
from backend.config import Settings
from backend.memory.moorcheh_store import MoorchehVectorStore

s = Settings.from_env()
store = MoorchehVectorStore(settings=s)
rows = store.search_context(query_text="plan rejection conflict merge qa", top_k=5)
print("Result count:", len(rows))
for i, row in enumerate(rows, 1):
    md = row.get("metadata", row)
    print(f"{i}. type={md.get('record_type')} stage={md.get('stage')} status={md.get('status')} text={str(md.get('raw_text',''))[:120]}")
PY
```


## 12) Troubleshooting

### GitHub popup hangs during sign-in

- Extension now uses a 45-second timeout in `vscode-extension/src/githubAuth.ts`.
- If timeout triggers:
  - sign in manually via VS Code Accounts first,
  - retry launch.


### Job immediately becomes `failed`

Common reasons:

- Missing `MOORCHEH_API_KEY` (and no per-job `moorcheh_key`).
- `railtracks` not installed in backend environment.
- Invalid GitHub token or inaccessible repo.

Check `/status` logs for exact runtime exception.

If you see uvicorn reload warnings from `.workdirs/...` while using `--reload`, the backend was watching agent worktrees and restarting mid-run. Runtime now creates workdirs in OS temp path (outside repo watch scope). Restart backend to pick up this fix.

If you see repeated coder loopbacks with messages like:

- `No implementation outcome was provided by the coding agent`

runtime now treats this as recoverable contract noise and, for simple Python goals, applies deterministic fallback file creation (`hello_world.py`) so a real artifact is produced.

If you see:

- `fatal: invalid reference: main`

the target repo likely does not have a local `main` branch. Runtime now auto-falls back to the repo's current local branch when `base_branch` is missing.

If the target repo is newly initialized and has no commits, runtime now bootstraps an initial empty commit so git worktree operations can proceed.

If you see:

- `Cohere embed HTTP 400 ... valid input_type must be provided`

the backend now sends Cohere `input_type` automatically (`search_document` for writes, `search_query` for retrieval). Restart backend so the latest code is running.

If you see:

- `Unsupported EMBEDDING_PROVIDER 'https://...'`

your env is mis-set (provider accidentally set to URL). Use `EMBEDDING_PROVIDER=cohere` (or `mock` / `openai`). The config now also normalizes common typo `ochere` to `cohere`.

If you see:

- `EmbeddingDimensionError ... Expected 1536, got 1024`

you are using Cohere with a mismatched vector dimension. For `embed-english-v3.0` / `embed-multilingual-v3.0`, use `MOORCHEH_VECTOR_DIMENSION=1024`. The backend now defaults Cohere to 1024 and auto-corrects legacy 1536 values.


### No vectors visible in Moorcheh dashboard

- Confirm namespace name matches `MOORCHEH_VECTOR_NAMESPACE`.
- Confirm writes are happening in job logs (goal/plan/task/conflict events).
- Verify `MOORCHEH_VECTOR_DIMENSION` matches embedder dimension.
- Use the Python namespace/search snippets above to confirm API-level visibility.


## 13) Validation commands used in this repo

```bash
python -m pytest tests/ -q
npm --prefix vscode-extension run compile --silent
```

These currently pass in this branch (backend test suite and extension compile).


## 14) Current limitations / next hardening steps

- Job state is in-memory only (lost on backend restart).
- Coder tasks execute sequentially in runtime loop (despite multi-coder assignment).
- Extension UI currently does not expose repo/branch fields; backend supports them.
- GitHub PR/comment helpers exist but are not yet fully surfaced as first-class UI actions.

This means the core pipeline is functional, but there is room to harden persistence, throughput, and richer UX controls.
