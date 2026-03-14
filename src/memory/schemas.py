"""
Memory record schemas for orchestration system.
Extends base SPM memory layer with orchestration-specific record types.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import json
import uuid


RecordType = Literal[
    "goal_record",
    "plan_record", 
    "plan_rejection_record",
    "approval_record",
    "task_record",
    "agent_state_record",
]


@dataclass
class MemoryRecord:
    """Base class for all memory records."""
    project_id: str
    record_type: RecordType = "goal_record"
    agent_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    status: Literal["open", "in_progress", "done", "blocked", "superseded"] = "open"
    importance: int = 3  # 1-5 scale
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Generated fields
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str = ""  # Natural language summary for semantic search
    
    def to_moorcheh_doc(self) -> Dict[str, Any]:
        """Convert to Moorcheh document format."""
        record_dict = asdict(self)
        return {
            "id": f"{self.record_type}:{self.project_id}:{self.timestamp}:{self.id}",
            "text": self.text or self._generate_summary(),
            "metadata": {
                "record_type": self.record_type,
                "project_id": self.project_id,
                "agent_id": self.agent_id,
                "importance": self.importance,
                "status": self.status,
            },
            "payload": self.payload,
            "timestamp": self.timestamp,
        }
    
    def _generate_summary(self) -> str:
        """Generate natural language summary from payload."""
        return f"{self.record_type}: {json.dumps(self.payload)[:200]}"


@dataclass
class GoalRecord(MemoryRecord):
    """Record of a user-provided goal."""
    record_type: RecordType = "goal_record"
    
    def __post_init__(self):
        if not self.text:
            self.text = self.payload.get("goal_description", "Goal record")


@dataclass
class PlanRecord(MemoryRecord):
    """Record of a generated plan for a goal."""
    record_type: RecordType = "plan_record"
    
    def __post_init__(self):
        if not self.text:
            goal = self.payload.get("goal_id", "unknown")
            steps = len(self.payload.get("steps", []))
            self.text = f"Plan for goal {goal} with {steps} steps"


@dataclass
class PlanRejectionRecord(MemoryRecord):
    """Record of a rejected plan."""
    record_type: RecordType = "plan_rejection_record"
    
    def __post_init__(self):
        if not self.text:
            reason = self.payload.get("rejection_reason", "Plan rejected")
            self.text = f"Plan rejected: {reason}"


@dataclass
class ApprovalRecord(MemoryRecord):
    """Record of approval/rejection decision."""
    record_type: RecordType = "approval_record"
    
    def __post_init__(self):
        if not self.text:
            decision = self.payload.get("decision", "unknown")
            plan_id = self.payload.get("plan_id", "unknown")
            self.text = f"Approval {decision} for plan {plan_id}"


@dataclass
class TaskRecord(MemoryRecord):
    """Record of a task assigned to an agent."""
    record_type: RecordType = "task_record"
    
    def __post_init__(self):
        if not self.text:
            task_name = self.payload.get("task_name", "Task")
            agent = self.agent_id or "unassigned"
            self.text = f"Task: {task_name} assigned to {agent}"


@dataclass
class AgentStateRecord(MemoryRecord):
    """Record of an agent's current state."""
    record_type: RecordType = "agent_state_record"
    
    def __post_init__(self):
        if not self.text:
            workload = len(self.payload.get("assigned_tasks", []))
            self.text = f"Agent {self.agent_id} has {workload} tasks"
