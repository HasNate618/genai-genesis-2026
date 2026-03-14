"""
FastAPI server for orchestration API.
Provides endpoints for goal creation, planning, approval, and task distribution.
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from datetime import datetime
import logging

from config import settings
from memory.store import MoorchehStore
from core.orchestration import OrchestrationEngine
from core.planning import PlanningCoordinator
from core.approval import ApprovalManager
from core.task_distributor import TaskDistributor
from api.models import (
    GoalRequest, GoalResponse,
    GeneratePlanRequest, PlanSubmissionRequest, PlanResponse,
    ApprovalDecisionRequest, ApprovalStatusResponse,
    TaskRequest, TasksListResponse,
    OrchestrationStatusResponse,
    AgentRegistrationRequest,
    HealthCheckResponse, ErrorResponse,
)

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Orchestration API",
    description="Multi-agent orchestration and coordination system",
    version="0.1.0",
)

# Global instances (will be initialized on startup)
store: MoorchehStore = None
engine: OrchestrationEngine = None
planning_coordinator: PlanningCoordinator = None
approval_manager: ApprovalManager = None
task_distributor: TaskDistributor = None


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global store, engine, planning_coordinator, approval_manager, task_distributor
    
    try:
        store = MoorchehStore(
            api_key=settings.moorcheh_api_key,
            base_url=settings.moorcheh_base_url,
            project_id=settings.project_id,
        )
        
        engine = OrchestrationEngine(store, settings.project_id)
        
        planning_coordinator = PlanningCoordinator(
            engine=engine,
            store=store,
            agent_webhook_base_url=settings.orchestration_agent_webhook_base_url,
            planning_timeout_seconds=settings.orchestration_max_planning_wait_seconds,
        )
        
        approval_manager = ApprovalManager(engine, store)
        
        task_distributor = TaskDistributor(
            engine=engine,
            store=store,
            agent_webhook_base_url=settings.orchestration_agent_webhook_base_url,
            assignment_strategy=settings.orchestration_task_assignment_strategy,
        )
        
        logger.info("Orchestration services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise


@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Check system health."""
    if not store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Services not initialized",
        )
    
    health_status = store.health_check()
    
    return HealthCheckResponse(
        status="healthy" if health_status.get("connected") else "degraded",
        moorcheh_connected=health_status.get("connected", False),
        fallback_available=health_status.get("fallback_available", False),
        timestamp=health_status.get("timestamp", datetime.utcnow().isoformat() + "Z"),
    )


# ==================== GOAL ENDPOINTS ====================

@app.post("/orchestration/goal", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(request: GoalRequest):
    """Create a new goal for orchestration."""
    try:
        goal_id = engine.create_goal(request.goal_description)
        context = engine.get_context(goal_id)
        
        return GoalResponse(
            goal_id=goal_id,
            goal_description=context.goal_description,
            state=context.state.value,
            created_at=context.created_at,
            updated_at=context.updated_at,
        )
    except Exception as e:
        logger.error(f"Failed to create goal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/orchestration/goal/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: str):
    """Get goal details."""
    context = engine.get_context(goal_id)
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal {goal_id} not found",
        )
    
    return GoalResponse(
        goal_id=goal_id,
        goal_description=context.goal_description,
        state=context.state.value,
        created_at=context.created_at,
        updated_at=context.updated_at,
    )


@app.delete("/orchestration/goal/{goal_id}", status_code=status.HTTP_200_OK)
async def cancel_goal(goal_id: str):
    """Cancel orchestration for a goal."""
    if not engine.cancel(goal_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal {goal_id} not found",
        )
    
    return {"message": f"Goal {goal_id} cancelled"}


# ==================== PLANNING ENDPOINTS ====================

@app.post("/orchestration/goal/{goal_id}/plan", status_code=status.HTTP_202_ACCEPTED)
async def trigger_planning(goal_id: str):
    """Trigger planning for a goal."""
    if not planning_coordinator.trigger_planning(goal_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger planning",
        )
    
    return {"message": "Planning triggered", "goal_id": goal_id}


@app.post("/orchestration/plan-submit", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def submit_plan(request: PlanSubmissionRequest):
    """
    Submit a generated plan from a planning agent.
    This is called by the planning agent after generating a plan.
    """
    try:
        plan_data = {
            "planning_agent_id": request.planning_agent_id,
            "steps": [step.dict() for step in request.steps],
            "effort_estimate": request.effort_estimate,
            "dependencies": request.dependencies or [],
            "risks": request.risks or [],
            "rationale": request.rationale or "",
        }
        
        plan_id = engine.store_plan(request.goal_id, plan_data)
        context = engine.get_context(request.goal_id)
        plan = context.plans[plan_id]
        
        return PlanResponse(
            plan_id=plan_id,
            goal_id=request.goal_id,
            planning_agent_id=request.planning_agent_id,
            steps=request.steps,
            effort_estimate=request.effort_estimate,
            dependencies=request.dependencies or [],
            risks=request.risks or [],
            rationale=request.rationale or "",
            created_at=plan.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )
    except Exception as e:
        logger.error(f"Failed to submit plan: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/orchestration/plans/{goal_id}")
async def get_plans(goal_id: str):
    """Get all plans for a goal."""
    plans = planning_coordinator.get_plans(goal_id)
    if not plans:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No plans found for goal {goal_id}",
        )
    
    return {
        "goal_id": goal_id,
        "plans": plans,
        "total_plans": len(plans),
    }


# ==================== APPROVAL ENDPOINTS ====================

@app.post("/orchestration/goal/{goal_id}/approve-plan", status_code=status.HTTP_200_OK)
async def approve_plan(goal_id: str, request: ApprovalDecisionRequest):
    """Approve a plan."""
    if not planning_coordinator.transition_to_review(goal_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot transition to review state",
        )
    
    if not approval_manager.approve_plan(goal_id, request.plan_id, request.notes):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve plan",
        )
    
    return {"message": "Plan approved", "goal_id": goal_id, "plan_id": request.plan_id}


@app.post("/orchestration/goal/{goal_id}/reject-plan", status_code=status.HTTP_200_OK)
async def reject_plan(goal_id: str, request: ApprovalDecisionRequest):
    """Reject a plan and return to planning."""
    if not approval_manager.reject_plan(goal_id, request.plan_id, request.notes):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject plan",
        )
    
    return {"message": "Plan rejected, returning to planning", "goal_id": goal_id}


@app.get("/orchestration/approval-status/{goal_id}", response_model=ApprovalStatusResponse)
async def get_approval_status(goal_id: str):
    """Get approval status for a goal."""
    status_data = approval_manager.get_approval_status(goal_id)
    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal {goal_id} not found",
        )
    
    return ApprovalStatusResponse(**status_data)


# ==================== TASK ENDPOINTS ====================

@app.post("/orchestration/distribute-tasks", status_code=status.HTTP_202_ACCEPTED)
async def distribute_tasks(goal_id: str):
    """Distribute tasks from approved plan."""
    if not task_distributor.distribute_tasks(goal_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to distribute tasks",
        )
    
    return {"message": "Tasks distributed", "goal_id": goal_id}


@app.get("/orchestration/tasks/{goal_id}", response_model=TasksListResponse)
async def get_tasks(goal_id: str):
    """Get all tasks for a goal."""
    context = engine.get_context(goal_id)
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal {goal_id} not found",
        )
    
    tasks = context.tasks
    if not tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No tasks found for goal {goal_id}",
        )
    
    task_responses = []
    for task_id, task_data in tasks.items():
        task_responses.append(
            # Import TaskResponse (already defined in models)
            {
                "task_id": task_id,
                "goal_id": goal_id,
                "assigned_agent_id": task_data.get("assigned_agent_id", "unknown"),
                "task_name": task_data.get("task_name", ""),
                "description": task_data.get("description", ""),
                "acceptance_criteria": task_data.get("acceptance_criteria", []),
                "dependencies": task_data.get("dependencies", []),
                "files_involved": task_data.get("files_involved", []),
                "effort_estimate": task_data.get("effort_estimate", "unknown"),
            }
        )
    
    return TasksListResponse(
        goal_id=goal_id,
        tasks=task_responses,
        total_tasks=len(task_responses),
    )


# ==================== STATUS ENDPOINTS ====================

@app.get("/orchestration/status/{goal_id}", response_model=OrchestrationStatusResponse)
async def get_orchestration_status(goal_id: str):
    """Get full orchestration status for a goal."""
    context = engine.get_context(goal_id)
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal {goal_id} not found",
        )
    
    return OrchestrationStatusResponse(
        goal_id=goal_id,
        goal_description=context.goal_description,
        state=context.state.value,
        created_at=context.created_at,
        updated_at=context.updated_at,
        total_plans=len(context.plans),
        approved_plan_id=context.approved_plan_id,
        total_tasks=len(context.tasks),
        error_message=context.error_message,
    )


# ==================== AGENT ENDPOINTS ====================

@app.post("/orchestration/agent/register", status_code=status.HTTP_200_OK)
async def register_agent(request: AgentRegistrationRequest):
    """Register an agent for task assignment."""
    task_distributor.register_agent(request.agent_id)
    
    return {
        "message": "Agent registered",
        "agent_id": request.agent_id,
        "capabilities": request.capabilities,
    }


@app.get("/orchestration/agents")
async def list_agents():
    """List all registered agents."""
    return {
        "agents": task_distributor.get_registered_agents(),
        "total": len(task_distributor.get_registered_agents()),
    }


# ==================== ROOT ENDPOINT ====================

@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "Orchestration API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
