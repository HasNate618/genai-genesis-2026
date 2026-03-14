from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from memory.semantic_store import memory_store
from agents.orchestrator import orchestrator

router = APIRouter()

class CreateProjectRequest(BaseModel):
    name: str

class CreateWorkflowRequest(BaseModel):
    project_id: str
    goal: str

class ApprovePlanRequest(BaseModel):
    workflow_id: str
    approved: bool

class RunWorkflowStepRequest(BaseModel):
    workflow_id: str

@router.post("/projects")
async def create_project(request: CreateProjectRequest):
    project = memory_store.create_project(request.name)
    return project

@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = memory_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.get("/projects/{project_id}/workflows")
async def get_project_workflows(project_id: str):
    workflows = memory_store.get_project_workflows(project_id)
    return workflows

@router.post("/workflows")
async def create_workflow(request: CreateWorkflowRequest):
    result = orchestrator.run_step1_goal(request.project_id, request.goal)
    return result

@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    workflow = memory_store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow

@router.post("/workflows/{workflow_id}/plan")
async def run_planning_step(workflow_id: str):
    result = orchestrator.run_step2_planning(workflow_id)
    return result

@router.post("/workflows/{workflow_id}/approve")
async def approve_plan(workflow_id: str, request: ApprovePlanRequest):
    workflow = memory_store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    if not request.approved:
        memory_store.update_workflow(workflow_id, current_step=2, status="planning")
        return {"status": "returned_to_planning", "message": "Plan denied, returning to step 2"}
    
    memory_store.update_workflow(workflow_id, current_step=4, status="approved")
    return {"status": "approved", "message": "Proceeding to task coordination"}

@router.post("/workflows/{workflow_id}/coordinate")
async def run_coordinating_step(workflow_id: str):
    result = orchestrator.run_step4_coordinating(workflow_id)
    return result

@router.post("/workflows/{workflow_id}/code")
async def run_coding_step(workflow_id: str, tasks: List[str]):
    result = orchestrator.run_step6_coding(workflow_id, tasks)
    return result

@router.post("/workflows/{workflow_id}/merge")
async def run_merging_step(workflow_id: str, coder_outputs: List[dict]):
    result = orchestrator.run_step7_merging(workflow_id, coder_outputs)
    return result

@router.post("/workflows/{workflow_id}/test")
async def run_testing_step(workflow_id: str, merged_code: str):
    result = orchestrator.run_step8_testing(workflow_id, merged_code)
    return result
