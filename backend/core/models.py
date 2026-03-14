from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime

class AgentRole(str, Enum):
    PLANNER = "planner"
    COORDINATOR = "coordinator"
    CODER = "coder"
    MERGER = "merger"
    QA_TESTER = "qa_tester"

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    COORDINATING = "coordinating"
    CODING = "coding"
    MERGING = "merging"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"

class Project(BaseModel):
    id: str
    name: str
    created_at: datetime
    workflows: List[str] = []

class Workflow(BaseModel):
    id: str
    project_id: str
    goal: str
    status: WorkflowStatus
    current_step: int
    created_at: datetime
    updated_at: datetime
    plans: Optional[List[str]] = None
    tasks: Optional[List[Dict[str, Any]]] = None

class Task(BaseModel):
    id: str
    workflow_id: str
    assigned_agent: str
    description: str
    status: str
    result: Optional[Dict[str, Any]] = None

class Plan(BaseModel):
    id: str
    workflow_id: str
    description: str
    approved: bool = False

class AgentConfig(BaseModel):
    role: AgentRole
    model: str
    tools: List[str]
    isolation_dir: Optional[str] = None
