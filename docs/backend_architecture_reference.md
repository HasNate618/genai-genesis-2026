# AgenticArmy — Backend Architecture Reference

This document provides a technical overview of the FastAPI backend and its communication protocol with the VS Code extension. It is designed as a reference for Phase 2, when the `asyncio.sleep()` mocks are replaced with actual `Railtracks` multi-agent workflows.

---

## 1. System Topology

The system operates on a **Client-Server Polling** model.

**The Client (VS Code Extension):**
- Written in TypeScript (Host) and HTML/CSS/JS (Webview UI).
- [backendClient.ts](file:///c:/Users/amirb/Documents/VScode/Genesis%2026/genai-genesis-2026/vscode-extension/src/backendClient.ts) handles all HTTP `fetch` requests.
- [panelManager.ts](file:///c:/Users/amirb/Documents/VScode/Genesis%2026/genai-genesis-2026/vscode-extension/src/panelManager.ts) (or [sidebarProvider.ts](file:///c:/Users/amirb/Documents/VScode/Genesis%2026/genai-genesis-2026/vscode-extension/src/sidebarProvider.ts)) manages a 2-second `setInterval` polling loop when a job is active.

**The Server (FastAPI):**
- Written in Python, running locally (`http://localhost:8000`).
- Manages an in-memory dictionary of state (`_jobs`), keyed by uniquely generated `job_id` UUIDs.
- Uses `asyncio.Event()` locks to pause background threads while waiting for Human-in-the-Loop HTTP callbacks.

---

## 2. The 3-Phase State Machine

A single `job_id` transitions through these exact string values in `job["status"]`. The UI parses these exact strings to highlight the active agent and render the review gates.

| Status String | Active Agent UI | Trigger Event |
| :--- | :--- | :--- |
| `initializing` | Planner | `POST /jobs` |
| `planning` | Planner | Background Task |
| `awaiting_plan_approval` | Planner | HitL 1 Pause (Waits for `POST /plan/review`) |
| `coordinating` | Conflict Mgr | HitL 1 Approved |
| `coding` | Coders | Background Task |
| `verifying` | Verification | Background Task |
| `review_ready` | Verification | HitL 2 Pause (Waits for `POST /result/review`) |
| `done` | *None (All Done)* | HitL 2 Approved / Merge completed |
| `failed` | *Error States* | Uncaught Exception |

---

## 3. Core Endpoints Reference

All endpoints are prefixed with `/api/v1`. The VS Code extension expects these specific response shapes.

### `GET /health`
- **Purpose:** Extension ping to verify the python server is alive before running.
- **Returns:** `{ "status": "ok", "service": "agentic-army-v1" }`

### `POST /jobs`
- **Purpose:** Initiates a new AI run.
- **Payload:** `{ "goal": string, "coder_count": int, "gemini_key": string, "moorcheh_key": string }`
- **Behavior:** 
  1. Creates job in `_jobs` dictionary.
  2. Spawns `asyncio.create_task(_run_pipeline())` as a fire-and-forget background thread.
- **Returns:** `{ "job_id": "uuid-string" }`

### `GET /jobs/{job_id}/plan`
- **Purpose:** Fetches the generated markdown plan for the Human-in-the-Loop review.
- **Behavior:** The extension *only* calls this once the `/status` poll returns `awaiting_plan_approval`.
- **Returns:** `{ "status": string, "plan": "Markdown string payload" }`

### `POST /jobs/{job_id}/plan/review`
- **Purpose:** Unblocks HitL 1.
- **Payload:** `{ "approved": boolean, "feedback": string }`
- **Behavior:** 
  1. Writes `job["plan_feedback"]` to state.
  2. Calls `_plan_events[job_id].set()` to wake up the background pipeline thread.
- **Returns:** `{ "ok": true }`

### `GET /jobs/{job_id}/status`
- **Purpose:** The main polling artery. Called every 2000ms by the extension.
- **Behavior:** The background pipeline thread constantly updates the `logs` append-only list, and the `agent_states` dictionary. This endpoint dumps that state to the client for live rendering.
- **Returns:** 
  ```json
  {
    "status": "coding",
    "logs": ["[10:00:00] Step started...", "[10:00:01] Coder running..."],
    "agentStates": {
      "planner": "done",
      "conflict_manager": "done",
      "coder": "running",
      "verification": "idle"
    }
  }
  ```

### `POST /jobs/{job_id}/result/review`
- **Purpose:** Unblocks HitL 2 (Final PR Delivery).
- **Payload:** `{ "approved": boolean, "feedback": string }`
- **Behavior:** 
  1. Writes `job["result_feedback"]` to state.
  2. Calls `_result_events[job_id].set()` to wake up the background pipeline thread to process the final Git merge or loop back to coding.
- **Returns:** `{ "ok": true }`

---

## 4. Hooking in Real Agents (Phase 2 Checklist)

When you are ready to replace [routes.py](file:///c:/Users/amirb/Documents/VScode/Genesis%2026/genai-genesis-2026/backend/api/routes.py) with real agents, here is precisely where the integrations belong:

1. **Replace `await asyncio.sleep(2)` in Phase 1:**
   - Instantiate your `PlannerLayer` (Railtracks).
   - Pass `req.goal` and `job["plan_feedback"]` to the LLM context.
   - Write the generated output to `job["plan"]`.

2. **Replace `asyncio.sleep` in Task Coordination:**
   - Make your Moorcheh API calls here. Extract vector embeddings for the files relevant to `job["plan"]`.
   - Chunk the work into JSON tasks.

3. **Replace Git Mocking in Parallel Coding:**
   - In Python, execute `git branch feature/XYZ` and `git checkout feature/XYZ`.
   - Spawn multiple async `CoderAgent` instances, passing them the specific chunked instructions and Moorcheh context.
   - Have them `git add .` and `git commit -m`. 

4. **Replace Verification Logic:**
   - Instead of a sleep, use Python's `subprocess` to run `pytest` or `npm run compile`.
   - Capture `stderr`. If `returncode != 0`, parse the stderr output, write it to the state, and `continue` your `while True` loop so it goes backward!

5. **Replace the Mock Final Delivery:**
   - If the user calls `/result/review` with `approved=True`, execute `git checkout main` and `git merge feature/XYZ`.
