# AgenticArmy Backend Architecture Reference

This document is the API/runtime contract for the current backend implementation.


## 1) Topology

AgenticArmy runs as a local FastAPI service (default `http://localhost:8000`) and is consumed by the VS Code extension.

- Extension starts jobs with `POST /api/v1/jobs`.
- Extension polls `GET /api/v1/jobs/{job_id}/status` every 2 seconds.
- Two human review gates are unblocked via:
  - `POST /api/v1/jobs/{job_id}/plan/review`
  - `POST /api/v1/jobs/{job_id}/result/review`


## 2) Runtime state machine

Exact statuses:

`initializing -> planning -> awaiting_plan_approval -> coordinating -> coding -> verifying -> review_ready -> done|failed`

Loopbacks:

- Plan rejection -> `planning`
- Conflict threshold breach -> `coordinating`
- Coding failure -> `coordinating`
- Merge failure -> `coordinating`
- QA failure -> `coordinating`
- Final result rejection -> `coordinating`


## 3) API endpoints (`/api/v1`)

## `GET /health`

Returns backend liveness:

```json
{ "status": "ok", "service": "agentic-army-v1" }
```


## `POST /jobs`

Starts a job pipeline.

Request:

```json
{
  "goal": "string (required)",
  "coder_count": 2,
  "gemini_key": "",
  "moorcheh_key": "",
  "github_token": "",
  "github_repo": "",
  "base_branch": "main"
}
```

Response:

```json
{ "job_id": "uuid" }
```

Notes:

- `gemini_key` and `moorcheh_key` are backward-compatible optional fields.
- Hosted LLM defaults are server-configured (`LLM_BASE_URL`, `LLM_MODEL`).
- `github_token` is expected from VS Code GitHub auth when using GitHub-integrated flow.


## `GET /jobs/{job_id}/plan`

Returns current plan payload:

```json
{
  "status": "awaiting_plan_approval",
  "plan": "markdown or planner output text"
}
```


## `POST /jobs/{job_id}/plan/review`

Unblocks plan HITL gate.

Request:

```json
{ "approved": true, "feedback": "optional" }
```

Response:

```json
{ "ok": true }
```


## `GET /jobs/{job_id}/status`

Polling payload consumed by extension:

```json
{
  "status": "coding",
  "logs": ["[12:00:01] ..."],
  "agentStates": {
    "planner": "done",
    "conflict_manager": "done",
    "coder": "running",
    "verification": "idle"
  },
  "agentResults": {
    "planner": "{...}",
    "conflict_manager": "{...}",
    "coder": "{...}",
    "verification": "{...}"
  }
}
```


## `POST /jobs/{job_id}/result/review`

Unblocks final HITL gate.

Request:

```json
{ "approved": true, "feedback": "optional" }
```

Response:

```json
{ "ok": true }
```


## 4) Core runtime modules

- `backend/core/job_runtime.py`
  - In-memory job registry.
  - Background pipeline and HITL event synchronization.
  - Railtracks phase calls and loopback handling.

- `backend/agents/railtracks_runtime.py`
  - Contract-driven agent calls for planner/coordinator/conflict/coder/merge/qa.
  - Structured outputs validated with Pydantic.

- `backend/core/workdir_runtime.py`
  - Isolated per-agent workdirs + branches.
  - Verification workdir created from merged coder branches.
  - Final merge to base branch on approval.

- `backend/core/tool_runtime.py`
  - Workspace-scoped tool execution with command/path guardrails.

- `backend/core/github_runtime.py`
  - Token-scoped GitHub API helper (identity + PR/comment operations).

- `backend/memory/*`
  - Moorcheh namespace provisioning, vector writes/searches, context reader/writer, conflict compensation.


## 5) Human-in-the-loop gates

The backend blocks on two `asyncio.Event`s per job:

- Plan gate (`awaiting_plan_approval`)
- Final result gate (`review_ready`)

These are only unblocked by corresponding review endpoints.


## 6) Extension integration expectations

The extension currently:

- Authenticates user via VS Code GitHub provider (`repo`, `read:user` scopes).
- Sends `github_token` in `POST /jobs`.
- Polls `GET /status` every 2s.
- Calls `GET /plan` only when status is `awaiting_plan_approval`.
- Expects exact status strings above.

Compatibility health checks:

- Tries `/api/v1/health` first.
- Falls back to `/health`.


## 7) Security and secret handling

- Runtime job state does not persist GitHub token or API keys.
- Extension optional keys are stored in VS Code secret storage.
- Tool runtime blocks path escape and dangerous git path flags.


## 8) Local validation commands

```bash
python -m pytest tests/ -q
npm --prefix vscode-extension run compile --silent
```

Current branch baseline: backend tests pass (`17`).
