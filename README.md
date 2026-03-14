# Multi-Agent Orchestration System

A Python FastAPI-based framework for coordinating and orchestrating work among independent coding agents. The system provides a structured workflow for goal decomposition, planning, approval, and task distribution using Moorcheh as the semantic memory backbone.

## Overview

The orchestration system implements a sophisticated workflow that guides multi-agent collaboration through controlled phases:

1. **Goal Input** - User/system provides a high-level goal
2. **Planning** - External planning agents generate implementation strategies
3. **Approval** - Plans are reviewed and approved or rejected (returns to planning if rejected)
4. **Task Distribution** - Approved plans are split into executable tasks and assigned to agents

## Architecture

### Core Components

- **OrchestrationEngine** - State machine managing the orchestration workflow
- **PlanningCoordinator** - Triggers external planning agents and collects results
- **ApprovalManager** - Handles plan approval/rejection workflows
- **TaskDistributor** - Breaks plans into tasks and assigns to agents
- **MoorchehStore** - Semantic memory backend with offline fallback
- **FastAPI Server** - REST API for agent integration

### State Machine

```
GOAL_CREATED
    ↓
  PLANNING ←────────┐
    ↓               │
PLAN_REVIEW         │
    ↓               │
    ├─→ APPROVED ─→ DISTRIBUTING_TASKS ─→ TASKS_ASSIGNED
    │
    └─→ REJECTED ────┘
```

### Memory Records

The system stores all orchestration events in Moorcheh using typed record schemas:

- `goal_record` - User-provided goals
- `plan_record` - Generated plans with steps and effort estimates
- `plan_rejection_record` - Rejected plans with reasoning
- `approval_record` - Approval/rejection decisions
- `task_record` - Individual tasks assigned to agents
- `agent_state_record` - Agent workload and status

## API Reference

### Goal Management

#### Create a Goal

```
POST /orchestration/goal
Content-Type: application/json

{
  "goal_description": "Refactor authentication module to use JWT"
}

Response:
{
  "goal_id": "goal_abc123",
  "goal_description": "Refactor authentication module to use JWT",
  "state": "goal_created",
  "created_at": "2026-03-14T15:00:00Z",
  "updated_at": "2026-03-14T15:00:00Z"
}
```

#### Get Goal Status

```
GET /orchestration/goal/{goal_id}

Response: (same as above)
```

#### Cancel Goal

```
DELETE /orchestration/goal/{goal_id}

Response:
{
  "message": "Goal {goal_id} cancelled"
}
```

### Planning Workflow

#### Trigger Planning

```
POST /orchestration/goal/{goal_id}/plan

Response (202 Accepted):
{
  "message": "Planning triggered",
  "goal_id": "{goal_id}"
}
```

The system will:
1. Query Moorcheh for similar past goals (for context)
2. Call the external planning agent with the goal and context
3. Store returned plans in memory

#### Submit Plan (Called by Planning Agent)

```
POST /orchestration/plan-submit
Content-Type: application/json

{
  "goal_id": "goal_abc123",
  "planning_agent_id": "planner_v1",
  "steps": [
    {
      "name": "Update JWT library",
      "description": "Update authentication library to v3.0",
      "acceptance_criteria": ["Tests pass", "No breaking changes"],
      "dependencies": ["Install dependencies"],
      "files": ["src/auth/jwt.py", "requirements.txt"]
    }
  ],
  "effort_estimate": "4 hours",
  "risks": ["May break existing auth flows"],
  "rationale": "JWT v3.0 has better performance"
}

Response:
{
  "plan_id": "plan_xyz789",
  "goal_id": "goal_abc123",
  ...plan data...
}
```

#### Get Plans for a Goal

```
GET /orchestration/plans/{goal_id}

Response:
{
  "goal_id": "goal_abc123",
  "plans": {
    "plan_xyz789": {...},
    "plan_xyz790": {...}
  },
  "total_plans": 2
}
```

### Approval Workflow

#### Get Plans for Approval

```
GET /orchestration/approval-status/{goal_id}

Response:
{
  "goal_id": "goal_abc123",
  "state": "plan_review",
  "total_plans": 2,
  "approved_plan_id": null,
  "plans_ready_for_approval": true
}
```

#### Approve a Plan

```
POST /orchestration/goal/{goal_id}/approve-plan
Content-Type: application/json

{
  "goal_id": "goal_abc123",
  "plan_id": "plan_xyz789",
  "decision": "approve",
  "notes": "Plan looks comprehensive. Go ahead."
}

Response:
{
  "message": "Plan approved",
  "goal_id": "goal_abc123",
  "plan_id": "plan_xyz789"
}
```

#### Reject a Plan (Returns to Planning)

```
POST /orchestration/goal/{goal_id}/reject-plan
Content-Type: application/json

{
  "goal_id": "goal_abc123",
  "plan_id": "plan_xyz789",
  "decision": "reject",
  "notes": "Effort estimate too high. Can you optimize?"
}

Response:
{
  "message": "Plan rejected, returning to planning",
  "goal_id": "goal_abc123"
}
```

### Task Distribution

#### Distribute Tasks

```
POST /orchestration/distribute-tasks?goal_id=goal_abc123

Response (202 Accepted):
{
  "message": "Tasks distributed",
  "goal_id": "goal_abc123"
}
```

The system will:
1. Parse approved plan into discrete tasks
2. Assign tasks to registered agents (round-robin or skill-based)
3. Send task notifications to each agent

#### Get Tasks for a Goal

```
GET /orchestration/tasks/{goal_id}

Response:
{
  "goal_id": "goal_abc123",
  "tasks": [
    {
      "task_id": "task_t1",
      "goal_id": "goal_abc123",
      "assigned_agent_id": "agent_1",
      "task_name": "Update JWT library",
      "description": "Update authentication library to v3.0",
      "acceptance_criteria": ["Tests pass"],
      "dependencies": [],
      "files_involved": ["src/auth/jwt.py"],
      "effort_estimate": "4 hours"
    }
  ],
  "total_tasks": 1
}
```

### Agent Management

#### Register an Agent

```
POST /orchestration/agent/register
Content-Type: application/json

{
  "agent_id": "agent_1",
  "capabilities": ["python", "testing", "refactoring"]
}

Response:
{
  "message": "Agent registered",
  "agent_id": "agent_1",
  "capabilities": ["python", "testing", "refactoring"]
}
```

#### List Registered Agents

```
GET /orchestration/agents

Response:
{
  "agents": ["agent_1", "agent_2", "agent_3"],
  "total": 3
}
```

### Full Orchestration Status

```
GET /orchestration/status/{goal_id}

Response:
{
  "goal_id": "goal_abc123",
  "goal_description": "Refactor authentication module to use JWT",
  "state": "tasks_assigned",
  "created_at": "2026-03-14T15:00:00Z",
  "updated_at": "2026-03-14T15:05:00Z",
  "total_plans": 1,
  "approved_plan_id": "plan_xyz789",
  "total_tasks": 3,
  "error_message": null
}
```

## Installation & Setup

### Prerequisites

- Python 3.9+
- Optional: Moorcheh account for semantic memory

### Installation

```bash
# Clone repository
git clone <repo-url>
cd genai-genesis-2026

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
# - Moorcheh API credentials (optional)
# - Orchestration server settings
# - Agent webhook URL
```

## Running the Service

### Development Mode

```bash
source venv/bin/activate
python src/main.py
```

Server will start on `http://0.0.0.0:8000` (configurable via `.env`)

API documentation available at `http://localhost:8000/docs`

### Production Mode

```bash
source venv/bin/activate
ENVIRONMENT=production DEBUG=false python src/main.py
```

Or with Gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:8000 src.api.server:app
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_orchestration.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

**Test Results:** 23 tests passing ✅

## Integration Guide

### For External Planning Agents

1. **Listen for Planning Requests**

   The planning coordinator will POST to your webhook:
   ```
   POST /orchestration/plan
   {
     "goal_id": "goal_abc123",
     "goal_description": "...",
     "similar_past_goals": [...]
   }
   ```

2. **Generate and Submit Plan**

   ```
   POST http://orchestration-server:8000/orchestration/plan-submit
   {
     "goal_id": "goal_abc123",
     "planning_agent_id": "your_agent_id",
     "steps": [...],
     ...
   }
   ```

### For Task-Executing Agents

1. **Register with the System**

   ```
   POST http://orchestration-server:8000/orchestration/agent/register
   {
     "agent_id": "executor_agent_1",
     "capabilities": ["python", "testing"]
   }
   ```

2. **Receive Task Assignments**

   The task distributor will POST notifications to your webhook:
   ```
   POST /orchestration/task-assigned
   {
     "goal_id": "goal_abc123",
     "task_id": "task_t1",
     "assigned_agent_id": "executor_agent_1",
     "task": {...}
   }
   ```

3. **Query Goal Context**

   ```
   GET http://orchestration-server:8000/orchestration/status/{goal_id}
   ```

## Memory System

### Moorcheh Integration

All orchestration events are stored in Moorcheh for semantic search and context retrieval:

- **Semantic Search**: `store.query_similar(query_text, top_k=5)`
- **Metadata Queries**: `store.query_by_metadata(record_type="plan_record", agent_id="agent_1")`
- **Fallback**: If Moorcheh is unavailable, records are stored locally in JSON format

### Memory Record Lifecycle

1. **Creation** - Events stored immediately with importance score
2. **Retrieval** - Semantic search provides similar past events for context
3. **Compaction** (Future) - Old events can be summarized and compressed
4. **Fallback** - Local JSON snapshots for offline resilience

## Error Handling

The API returns structured error responses:

```json
{
  "error": "Goal not found",
  "detail": "Goal goal_abc123 does not exist",
  "timestamp": "2026-03-14T15:00:00Z"
}
```

HTTP Status Codes:
- `200` - Success
- `201` - Resource created
- `202` - Request accepted (async processing)
- `400` - Bad request (invalid state transition)
- `404` - Resource not found
- `500` - Server error
- `503` - Service unavailable (Moorcheh down, graceful degradation active)

## Project Structure

```
src/
  api/
    server.py              # FastAPI endpoints
    models.py              # Pydantic request/response schemas
  core/
    orchestration.py       # State machine engine
    planning.py            # Planning coordinator
    approval.py            # Approval manager
    task_distributor.py    # Task assignment logic
  memory/
    store.py               # Moorcheh wrapper + fallback
    schemas.py             # Memory record types
    index.py               # SQLite index (optional)
  config.py                # Configuration management
  main.py                  # Entry point

tests/
  conftest.py              # Pytest fixtures
  test_orchestration.py    # Engine tests
  test_planning.py         # Planning coordinator tests
  test_approval.py         # Approval manager tests
  test_task_distributor.py # Task distributor tests

requirements.txt           # Dependencies
pytest.ini                 # Test configuration
.env.example               # Configuration template
```

## Future Enhancements (Phase 2+)

- **Conflict Analysis** - Detect and score task conflicts before assignment
- **Merge Coordination** - Coordinate merging of agent commits
- **QA Integration** - Automated testing and validation
- **Skill-Based Assignment** - Intelligent task allocation based on agent capabilities
- **Async Task Queue** - Background job processing with Celery/Redis
- **Metrics Dashboard** - Real-time visualization of orchestration progress
- **Docker Support** - Containerization for production deployment

## Contributing

1. Create a feature branch
2. Add tests for new functionality
3. Ensure all tests pass: `pytest tests/`
4. Submit pull request with description

## License

See LICENSE file for details.

## Support

For issues or questions:
1. Check existing GitHub issues
2. Review API documentation at `/docs` endpoint
3. Check test examples in `tests/` directory
