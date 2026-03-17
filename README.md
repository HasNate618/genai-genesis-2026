# AgenticArmy (Genesis 2026)

AgenticArmy is a **human-in-the-loop, multi-agent coding pipeline** with a **VS Code extension UI** and a **local FastAPI backend**.

It’s built to answer one practical question: **how do you run multiple “coder agents” in parallel without them constantly conflicting, duplicating work, or losing context?**

This repo contains:
- **`vscode-extension/`**: the VS Code extension (sidebar + commands) that starts jobs, shows logs, and handles approvals.
- **`backend/`**: the FastAPI service that runs the job state machine and coordinates agent phases.
- **`docs/`**: architecture and integration references (recommended reading).

---

## What it does

- **Goal → Plan → Approve → Execute → Verify → Approve**
- Two explicit human approval gates:
  - **Plan approval** (`awaiting_plan_approval`)
  - **Final result approval** (`review_ready`)
- A backend **state machine** that supports loopbacks (plan rejection, conflict risk too high, merge failure, QA failure, etc.).
- Supports multiple runtime modes:
  - **Simulation mode** for local/UI testing without burning LLM quota.
  - **Agent runtime mode** that can call real agents via contract execution (default) or Railtracks.

---

## Architecture (high level)

### Components
- **VS Code extension**
  - Collects the goal and settings (API keys/tokens)
  - Calls backend endpoints (`/api/v1/...`)
  - Polls job status and renders logs + results
- **FastAPI backend**
  - Owns job lifecycle + HITL gates (`asyncio.Event`)
  - Runs phases: planner → coordinator → conflict analysis → coders → merge → QA
  - Exposes a stable `/api/v1` contract consumed by the extension

### Job statuses

Exact runtime statuses (as consumed by the extension):

`initializing → planning → awaiting_plan_approval → coordinating → analyzing_conflicts → coding → merging → verifying → review_ready → done|failed`

---

## Quickstart (Windows / PowerShell)

### Prerequisites
- **Python 3.10+**
- **Node.js 18+** (for the VS Code extension)
- **VS Code** (to run the extension UI)

### 1) Backend setup

From `genai-genesis-2026/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional environment variables:

```powershell
copy .env.example .env
```

Start the backend:

```powershell
python -m backend.main
```

Health checks:
- `GET http://127.0.0.1:8000/api/v1/health`
- fallback: `GET http://127.0.0.1:8000/health`

### 2) Extension setup

```powershell
cd vscode-extension
npm install
npm run compile
```

To run the extension:
- Open `genai-genesis-2026/` in VS Code
- Open the extension folder `vscode-extension/`
- Press **F5** (Run Extension) to launch an “Extension Development Host”
- In the new VS Code window, open the **AgenticArmy** sidebar (⚡ icon)

---

## Configuration

### Backend environment
- **`AGENTIC_ARMY_AGENT_RUNTIME`**
  - **`contract`** (default): contract-driven agent execution path
  - **`railtracks`**: Railtracks agent nodes with role-scoped tools
- **`AGENTIC_ARMY_SIMULATE=1`**: forces simulation mode (no real agent calls)
- **`AGENTIC_ARMY_GEMINI_MODEL`**: optional model override for the agent runtime
- **`AGENTIC_ARMY_CODING_PARALLELISM`**: caps concurrent coding calls (defaults to safer/sequential behavior in real-agent mode)

### `.env` keys (optional)
See `.env.example` for Moorcheh + embeddings + hosted LLM defaults. The backend is designed to avoid persisting secrets in job state.

---

## API (used by the VS Code extension)

Base path: **`/api/v1`**

- **`POST /jobs`**: start a job
  - Payload supports: `goal`, `coder_count`, `gemini_key`, `moorcheh_key`, `github_token`, `github_repo`, `base_branch`, `workspace_path`
  - Returns: `{ "job_id": "..." }`
- **`GET /jobs/{job_id}/plan`**: get the plan when awaiting approval
- **`POST /jobs/{job_id}/plan/review`**: approve/reject plan (unblocks gate)
- **`GET /jobs/{job_id}/status`**: polling payload (logs + agent states + artifacts)
- **`POST /jobs/{job_id}/result/review`**: approve/reject final result (unblocks gate)

For the canonical contract and examples, see `docs/backend_architecture_reference.md`.

---

## Testing

From `genai-genesis-2026/`:

```powershell
pytest -q
```

---

## Repo layout

```text
genai-genesis-2026/
  backend/                 # FastAPI service + runtimes + memory layer
  vscode-extension/        # VS Code extension (sidebar + commands)
  docs/                    # Architecture + integration references
  tests/                   # Backend tests
  .env.example
  requirements.txt
```

---

## Docs worth reading

- `docs/backend_architecture_reference.md`: API + runtime contract (extension-facing)
- `docs/question-and-answer.md`: project Q&A and context
- `docs/human-summary.md`: short non-technical summary

---

## License

See `LICENSE`.
