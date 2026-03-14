# Integration Examples

This directory contains example scripts for integrating with the orchestration system.

## Planning Agent Example

A simple example of an external planning agent that integrates with the orchestration system:

```python
import httpx
import json
import asyncio

class PlanningAgent:
    def __init__(self, agent_id: str, orchestration_url: str):
        self.agent_id = agent_id
        self.orchestration_url = orchestration_url
    
    async def listen_for_planning_requests(self):
        """Listen for planning requests from the orchestration server."""
        # This would be your FastAPI server listening on /orchestration/plan
        pass
    
    async def generate_plan(self, goal_id: str, goal_description: str, similar_goals: list) -> dict:
        """Generate a plan for the given goal."""
        # Implement your planning logic here
        plan = {
            "goal_id": goal_id,
            "planning_agent_id": self.agent_id,
            "steps": [
                {
                    "name": "Step 1",
                    "description": "Description of step 1",
                    "acceptance_criteria": ["Requirement 1"],
                    "dependencies": [],
                    "files": ["src/module.py"]
                }
            ],
            "effort_estimate": "4 hours",
            "risks": ["Risk 1"],
            "rationale": "Why this plan makes sense"
        }
        return plan
    
    async def submit_plan(self, plan: dict):
        """Submit the generated plan back to the orchestration system."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.orchestration_url}/orchestration/plan-submit",
                json=plan
            )
            return response.json()
```

## Executing Agent Example

An example of an agent that receives and executes tasks:

```python
import httpx
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class TaskAssignmentNotification(BaseModel):
    goal_id: str
    task_id: str
    assigned_agent_id: str
    task: dict

@app.post("/orchestration/task-assigned")
async def receive_task(notification: TaskAssignmentNotification):
    """Receive a task assignment from the orchestration system."""
    task = notification.task
    
    # Execute the task
    result = await execute_task(task)
    
    return {
        "status": "acknowledged",
        "task_id": notification.task_id,
        "result": result
    }

async def execute_task(task: dict) -> dict:
    """Execute the assigned task."""
    # Implement your task execution logic here
    return {
        "status": "completed",
        "output": "Task completed successfully"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

## Complete Workflow Example

Here's a complete example of orchestrating a multi-agent workflow:

```python
import httpx
import time

async def orchestrate_workflow():
    """Example of a complete orchestration workflow."""
    
    orchestration_url = "http://localhost:8000"
    
    # Step 1: Create a goal
    async with httpx.AsyncClient() as client:
        # Create goal
        goal_response = await client.post(
            f"{orchestration_url}/orchestration/goal",
            json={"goal_description": "Refactor authentication to use JWT"}
        )
        goal = goal_response.json()
        goal_id = goal["goal_id"]
        print(f"Created goal: {goal_id}")
        
        # Step 2: Register agents
        await client.post(
            f"{orchestration_url}/orchestration/agent/register",
            json={"agent_id": "planner_1", "capabilities": ["planning"]}
        )
        await client.post(
            f"{orchestration_url}/orchestration/agent/register",
            json={"agent_id": "executor_1", "capabilities": ["python"]}
        )
        
        # Step 3: Trigger planning
        plan_response = await client.post(
            f"{orchestration_url}/orchestration/goal/{goal_id}/plan"
        )
        print(f"Planning triggered: {plan_response.json()}")
        
        # Wait for planning (in real system, polling or webhooks)
        await asyncio.sleep(2)
        
        # Step 4: Get plans
        plans_response = await client.get(
            f"{orchestration_url}/orchestration/plans/{goal_id}"
        )
        plans = plans_response.json()
        print(f"Generated {plans['total_plans']} plan(s)")
        
        # Step 5: Approve first plan
        first_plan_id = list(plans["plans"].keys())[0]
        await client.post(
            f"{orchestration_url}/orchestration/goal/{goal_id}/approve-plan",
            json={
                "goal_id": goal_id,
                "plan_id": first_plan_id,
                "decision": "approve",
                "notes": "Looks good!"
            }
        )
        print(f"Approved plan: {first_plan_id}")
        
        # Step 6: Distribute tasks
        await client.post(
            f"{orchestration_url}/orchestration/distribute-tasks?goal_id={goal_id}"
        )
        print("Tasks distributed")
        
        # Step 7: Get final status
        status_response = await client.get(
            f"{orchestration_url}/orchestration/status/{goal_id}"
        )
        status = status_response.json()
        print(f"Final status: {status['state']} with {status['total_tasks']} tasks")

if __name__ == "__main__":
    import asyncio
    asyncio.run(orchestrate_workflow())
```

## Testing the API

Using curl to test endpoints:

```bash
# Health check
curl http://localhost:8000/health

# Create a goal
curl -X POST http://localhost:8000/orchestration/goal \
  -H "Content-Type: application/json" \
  -d '{"goal_description": "Implement feature X"}'

# Get goal status
curl http://localhost:8000/orchestration/goal/goal_abc123

# Trigger planning
curl -X POST http://localhost:8000/orchestration/goal/goal_abc123/plan

# Get plans
curl http://localhost:8000/orchestration/plans/goal_abc123

# Approve a plan
curl -X POST http://localhost:8000/orchestration/goal/goal_abc123/approve-plan \
  -H "Content-Type: application/json" \
  -d '{
    "goal_id": "goal_abc123",
    "plan_id": "plan_xyz789",
    "decision": "approve",
    "notes": "Approved"
  }'

# Distribute tasks
curl -X POST "http://localhost:8000/orchestration/distribute-tasks?goal_id=goal_abc123"

# Get tasks
curl http://localhost:8000/orchestration/tasks/goal_abc123

# Get full status
curl http://localhost:8000/orchestration/status/goal_abc123

# Register agent
curl -X POST http://localhost:8000/orchestration/agent/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent_1",
    "capabilities": ["python", "testing"]
  }'

# List agents
curl http://localhost:8000/orchestration/agents
```
