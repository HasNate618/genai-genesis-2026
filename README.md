# AgenticArmy
Making AI agents work together properly.

## Notes to devs
Tell your agent to check docs/question-and-answer.md, as it should help with its context given the additional information about future project structure. Note that because infastructure plans have changed so many times, it may have lost relevance.

## Key points
Agents: Planner, Coordinator, Conflict Analyst, Coder(s), Merger, QA Tester

## Tech stack
- Vscode extension
- [RailTracks for agent orchestration](https://github.com/RailtownAI/railtracks/)
- [Moorcheh agent memory SDK](https://github.com/moorcheh-ai/moorcheh-python-sdk)

## Backend runtime modes
- `AGENTIC_ARMY_AGENT_RUNTIME=contract` (default): uses Gemini markdown-contract execution path.
- `AGENTIC_ARMY_AGENT_RUNTIME=railtracks`: uses Railtracks agent nodes with role-scoped tools.

### Railtracks tool permissions by role
- Planner / Coordinator / Conflict Analyst: `read`, `glob`, `grep`
- Coding / Merge / QA: `read`, `write`, `edit`, `bash`, `glob`, `grep`

### Safety controls
- Writes default to per-agent isolated workspaces under `.agent_workspaces/`
- Repository writes require explicit `repo/...` path prefix
- Path traversal is blocked, and command execution is limited to an allowlisted binary set

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
