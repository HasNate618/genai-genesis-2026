# AgenticArmy
Making AI agents work together properly. 

## Key points
Agents: Planning, coordinator, conflict analyst, coder(s), merger, (QA) tester

## Tech stack
Vscode extension (node.js, webview ui toolkit) - local orchestrator
Handles user’s personal agent registration
Task interface
Tool injection
Python backend with FastAPI
Exposes tools
Agentic pipeline
Mastra for agent orchestration

## Synopsis
Basic workflow:
1. Human provides goal; high-level process, success metrics, etc. Move on.
2. Planning agent runs; finds ways the goal can be implemented. Move on.
3. Prompt humans to approve/deny plans. If denied, return to step 2. If approved, move on.
4. Task coordinator agent runs; Splits up tasks among the agents to achieve the goal. Move on.
5. Conflict analysis agent runs, and tasks are assigned a conflict score based on how likely agents are to overwrite each other’s work. If a threshold is reached, return to step 4 to reassign agents (merge tasks?). If not, move on.
6. Coding agents run; tasks are completed in isolated environments. Move on.
7. Merge agent runs; merges individual agent commits. If it is too difficult, return to step 4. Else, move on.
8. QA agent runs; tests code for functionality. If unsuccessful, return to step 6. If successful, the process is finished until the next iteration.
