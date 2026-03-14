"""
Task distributor: breaks approved plans into tasks and assigns them to agents.
"""

import httpx
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid

from memory.store import MoorchehStore
from memory.schemas import AgentStateRecord
from core.orchestration import OrchestrationEngine

logger = logging.getLogger(__name__)


class TaskDistributor:
    """Manages task creation and assignment."""
    
    def __init__(self,
                 engine: OrchestrationEngine,
                 store: MoorchehStore,
                 agent_webhook_base_url: str,
                 assignment_strategy: str = "round_robin"):
        """
        Initialize task distributor.
        
        Args:
            engine: OrchestrationEngine instance
            store: MoorchehStore instance
            agent_webhook_base_url: Base URL where agents listen
            assignment_strategy: How to assign tasks ("round_robin", "skill_based", "random")
        """
        self.engine = engine
        self.store = store
        self.agent_webhook_base_url = agent_webhook_base_url
        self.assignment_strategy = assignment_strategy
        self.known_agents: List[str] = []  # Will be populated from agent registry
    
    def distribute_tasks(self, goal_id: str) -> bool:
        """
        Distribute tasks from approved plan.
        
        Args:
            goal_id: Goal identifier
        
        Returns:
            True if distribution succeeded
        """
        context = self.engine.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            return False
        
        if not context.approved_plan_id:
            logger.error(f"No approved plan for goal {goal_id}")
            return False
        
        approved_plan = context.plans.get(context.approved_plan_id)
        if not approved_plan:
            logger.error(f"Approved plan {context.approved_plan_id} not found")
            return False
        
        # Transition to distributing state
        context.state = context.state.__class__.DISTRIBUTING_TASKS
        context.updated_at = datetime.utcnow().isoformat() + "Z"
        
        # Parse plan steps into tasks
        tasks = self._parse_plan_into_tasks(goal_id, approved_plan)
        
        if not tasks:
            logger.error(f"Failed to parse plan into tasks")
            self.engine.set_failed(goal_id, "Failed to parse plan into tasks")
            return False
        
        # Assign tasks to agents
        assignments = self._assign_tasks_to_agents(tasks)
        
        # Create task records and notify agents
        success = True
        for task, agent_id in assignments:
            try:
                task["assigned_agent_id"] = agent_id
                task_id = self.engine.create_task(goal_id, task)
                
                # Notify agent
                if not self._notify_agent(agent_id, goal_id, task_id, task):
                    logger.warning(f"Failed to notify agent {agent_id} of task {task_id}")
                    success = False
                    
            except Exception as e:
                logger.error(f"Failed to create/assign task: {e}")
                success = False
        
        if success:
            self.engine.transition_to_tasks_assigned(goal_id)
            logger.info(f"Successfully distributed {len(tasks)} tasks for goal {goal_id}")
        else:
            self.engine.set_failed(goal_id, "Failed to distribute all tasks")
        
        return success
    
    def _parse_plan_into_tasks(self, goal_id: str, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse plan steps into executable tasks.
        
        Args:
            goal_id: Goal identifier
            plan: Plan data
        
        Returns:
            List of task dictionaries
        """
        tasks = []
        steps = plan.get("steps", [])
        
        for i, step in enumerate(steps):
            task = {
                "task_name": step.get("name", f"Task {i+1}"),
                "description": step.get("description", ""),
                "acceptance_criteria": step.get("acceptance_criteria", []),
                "dependencies": step.get("dependencies", []),
                "files_involved": step.get("files", []),
                "effort_estimate": step.get("effort_estimate", "unknown"),
                "step_index": i,
            }
            tasks.append(task)
        
        logger.debug(f"Parsed {len(tasks)} tasks from plan")
        return tasks
    
    def _assign_tasks_to_agents(self, tasks: List[Dict[str, Any]]) -> List[tuple]:
        """
        Assign tasks to agents based on strategy.
        
        Args:
            tasks: List of task dictionaries
        
        Returns:
            List of (task, agent_id) tuples
        """
        if not self.known_agents:
            # Fallback: use placeholder agents
            logger.warning("No known agents, using placeholder agents")
            self.known_agents = ["agent_1", "agent_2", "agent_3"]
        
        assignments = []
        
        if self.assignment_strategy == "round_robin":
            for i, task in enumerate(tasks):
                agent_id = self.known_agents[i % len(self.known_agents)]
                assignments.append((task, agent_id))
        
        elif self.assignment_strategy == "random":
            import random
            for task in tasks:
                agent_id = random.choice(self.known_agents)
                assignments.append((task, agent_id))
        
        else:  # Default to round_robin
            for i, task in enumerate(tasks):
                agent_id = self.known_agents[i % len(self.known_agents)]
                assignments.append((task, agent_id))
        
        logger.info(f"Assigned {len(assignments)} tasks using {self.assignment_strategy} strategy")
        return assignments
    
    def _notify_agent(self, agent_id: str, goal_id: str, task_id: str, task_data: Dict[str, Any]) -> bool:
        """
        Notify an agent of a task assignment.
        
        Args:
            agent_id: Agent identifier
            goal_id: Goal identifier
            task_id: Task identifier
            task_data: Task details
        
        Returns:
            True if notification succeeded
        """
        agent_webhook = f"{self.agent_webhook_base_url}/orchestration/task-assigned"
        
        notification = {
            "goal_id": goal_id,
            "task_id": task_id,
            "assigned_agent_id": agent_id,
            "task": task_data,
        }
        
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(agent_webhook, json=notification)
                response.raise_for_status()
                logger.debug(f"Notified agent {agent_id} of task {task_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to notify agent {agent_id}: {e}")
            return False
    
    def register_agent(self, agent_id: str) -> bool:
        """
        Register an agent for task assignment.
        
        Args:
            agent_id: Agent identifier
        
        Returns:
            True if registration succeeded
        """
        if agent_id not in self.known_agents:
            self.known_agents.append(agent_id)
            logger.info(f"Registered agent {agent_id}")
            return True
        return True
    
    def get_registered_agents(self) -> List[str]:
        """Get list of registered agents."""
        return self.known_agents.copy()
    
    def update_agent_state(self, agent_id: str, project_id: str, assigned_tasks: List[str]) -> bool:
        """
        Update agent state in memory.
        
        Args:
            agent_id: Agent identifier
            project_id: Project identifier
            assigned_tasks: List of assigned task IDs
        
        Returns:
            True if update succeeded
        """
        try:
            agent_record = AgentStateRecord(
                project_id=project_id,
                agent_id=agent_id,
                payload={
                    "assigned_tasks": assigned_tasks,
                    "workload": len(assigned_tasks),
                }
            )
            self.store.store_record(agent_record)
            return True
        except Exception as e:
            logger.error(f"Failed to update agent state: {e}")
            return False
