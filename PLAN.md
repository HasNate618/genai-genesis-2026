# AgenticArmy Project Plan

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

3. **Agent Orchestration** (Railword)
   - Planning Agent
   - Coordinator Agent
   - Conflict Analyst Agent
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
- Threshold-based gating **(20% likliness of similarity)**
- If threshold exceeded, return to Step 4
- Otherwise, proceed to execution

#### **Equation used:**

```
riskScore = [(numOfSharedDependencies * 0.2) + (percentageOfTaskSimilarity * 0.5) + (isSameCategoryTask * 0.3)]
```

This equation works by weighting three core metrics:
1. Shared dependencies; if two tasks require similar dependencies, it's plausible that they are the same (or at least similar). Lowly weighted.
2. Semantic similarity of task summaries; if tasks are semantically similar, then they're similar... *Proof: Obvious*. Highly weighted due to raw simplicity and reliability.
3. Identical task categories; all tasks have to fall into a category of {Fix, Feature, Refactor} etc. If tasks are of a different category, it is quite likley that they are not the same task and thus will probably not have similar implementations.  

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
