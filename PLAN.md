# AgenticArmy Implementation Plan

## Project Overview
Multi-agent collaboration system with human-in-the-loop approval workflow for automated code generation and testing.

## Architecture

### Components
1. **VSCode Extension** (Node.js + Webview UI Toolkit)
   - Local orchestrator
   - User task interface
   - Agent registration UI
   - Tool injection management

2. **Python Backend** (FastAPI)
   - REST API endpoints
   - Agentic pipeline execution
   - Tool exposure

3. **Agent Orchestration** (Mastra)
   - Planning Agent
   - Coordinator Agent
   - Coder Agents (multiple)
   - Merger Agent
   - QA Tester Agent

## Workflow Implementation

### Step 1: Goal Input
- Human provides goal via VSCode extension
- Goal stored in workflow context

### Step 2: Planning Agent
- Analyzes goal
- Generates implementation plans
- Stores plans in semantic memory

### Step 3: Human Approval
- Display plans in VSCode WebView
- Prompt for approve/deny
- If denied, loop to Step 2
- If approved, proceed

### Step 4: Task Coordination
- Coordinator agent splits goal into tasks
- Assigns tasks to coder agents
- Considers agent capabilities/availability

### Step 5: Conflict Analysis
- Calculate conflict scores based on file overlap
- Threshold-based gating
- If threshold exceeded, return to Step 4
- Otherwise, proceed to execution

### Step 6: Parallel Coding
- Coder agents work in isolated environments
- Each has own workspace
- Changes tracked in semantic memory

### Step 7: Merge
- Merger agent combines individual commits
- Handle conflicts
- If too difficult, return to Step 4
- Otherwise, proceed

### Step 8: QA Testing
- Run automated tests
- If failed, return to Step 6
- If passed, workflow complete

## Semantic Memory Layer

### Purpose
- Store agent context, decisions, and history
- Enable conflict detection
- Track file ownership

### Data Model
- Goals and plans
- Task assignments
- Agent states
- File change history
- Conflict metadata

## File Structure
```
/agentic-army/
  /vscode-extension/
    /src/
      extension.ts
      webview/
      agent-manager.ts
      task-interface.ts
  /backend/
    /api/
      routes.py
    /agents/
      planner.py
      coordinator.py
      coder.py
      merger.py
      qa_tester.py
    /memory/
      semantic_store.py
      conflict_detector.py
    main.py
```

## Implementation Phases

### Phase 1: Core Infrastructure
- FastAPI setup
- Basic Mastra agent definitions
- VSCode extension skeleton

### Phase 2: Agent Communication
- Message passing between agents
- State management
- Basic task distribution

### Phase 3: Semantic Memory
- Vector store integration (Moorcheh)
  - **Status: COMPLETE** ✅
  - Implemented: vector-memory scaffold with deterministic record schema, embedding provider (mock + OpenAI-compatible), **Moorcheh Python SDK client wrapper**, store façade, context reader/writer, conflict compensator, telemetry, FastAPI debug endpoints, and comprehensive unit tests.
  - All 7 tests pass locally.
  - Live integration test (2026-03-14): namespace provision ✓, vector upload ✓, search ✓, health check ✓
  - Key change: Switched from custom REST client to official `moorcheh-sdk` for automatic auth, retry logic, and type safety.
  - Docs updated: docs/Moorcheh.md now describes SDK usage, live test results, and architecture diagram.
- Conflict detection logic
- File tracking

### Phase 4: Human Integration
- Approval UI
- Task interface
- Real-time updates

### Phase 5: Testing & Refinement
- End-to-end workflows
- Conflict resolution improvements
- Performance optimization

Live Moorcheh integration test results (2026-03-14):
- Initial REST client attempts: namespace provision ✓, but vector upload ✗ (401/403 auth errors)
- Switched to official `moorcheh-sdk`: all operations ✓ (list, provision, upload, search, health)
- 3 test vectors uploaded successfully with metadata (workflow_id, record_type, agent_id)
- Search returned results with correct metadata preservation
- Decision: SDK integration complete. Future work: wire context writer/reader into orchestration runtime.

