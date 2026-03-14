"""
Planning coordinator: triggers planning agents and collects results.
"""

import httpx
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from memory.store import MoorchehStore
from core.orchestration import OrchestrationEngine

logger = logging.getLogger(__name__)


class PlanningCoordinator:
    """Manages planning workflow with external agents."""
    
    def __init__(self, 
                 engine: OrchestrationEngine,
                 store: MoorchehStore,
                 agent_webhook_base_url: str,
                 planning_timeout_seconds: int = 60):
        """
        Initialize planning coordinator.
        
        Args:
            engine: OrchestrationEngine instance
            store: MoorchehStore instance
            agent_webhook_base_url: Base URL where agents listen
            planning_timeout_seconds: Timeout for planning agent response
        """
        self.engine = engine
        self.store = store
        self.agent_webhook_base_url = agent_webhook_base_url
        self.planning_timeout_seconds = planning_timeout_seconds
    
    def trigger_planning(self, goal_id: str) -> bool:
        """
        Trigger planning for a goal.
        Queries similar past goals from memory, then calls external planning agent.
        
        Args:
            goal_id: Goal identifier
        
        Returns:
            True if planning was triggered
        """
        context = self.engine.get_context(goal_id)
        if not context:
            logger.error(f"Goal {goal_id} not found")
            return False
        
        if not self.engine.trigger_planning(goal_id):
            return False
        
        # Query memory for similar goals (for context)
        similar_goals = self.store.query_similar(
            query_text=context.goal_description,
            top_k=3
        )
        
        logger.info(f"Found {len(similar_goals)} similar past goals for context")
        
        # Prepare payload for planning agent
        planning_request = {
            "goal_id": goal_id,
            "goal_description": context.goal_description,
            "similar_past_goals": similar_goals,
        }
        
        # Call external planning agent
        plan_id = self._call_planning_agent(goal_id, planning_request)
        
        if plan_id:
            logger.info(f"Planning triggered for goal {goal_id}, received plan {plan_id}")
            return True
        else:
            logger.error(f"Planning agent failed for goal {goal_id}")
            self.engine.set_failed(goal_id, "Planning agent request failed")
            return False
    
    def _call_planning_agent(self, goal_id: str, planning_request: Dict[str, Any]) -> Optional[str]:
        """
        Call external planning agent.
        
        Args:
            goal_id: Goal identifier
            planning_request: Request payload
        
        Returns:
            Plan ID if successful, None otherwise
        """
        agent_url = f"{self.agent_webhook_base_url}/orchestration/plan"
        
        try:
            with httpx.Client(timeout=self.planning_timeout_seconds) as client:
                response = client.post(agent_url, json=planning_request)
                response.raise_for_status()
                
                result = response.json()
                plan_id = result.get("plan_id")
                
                if plan_id:
                    # Store the plan
                    self._store_plan_from_agent(goal_id, result)
                    return plan_id
                else:
                    logger.error(f"No plan_id in agent response: {result}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error(f"Planning agent timeout for goal {goal_id}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Planning agent request error for goal {goal_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling planning agent: {e}")
            return None
    
    def _store_plan_from_agent(self, goal_id: str, plan_response: Dict[str, Any]):
        """
        Store plan data from agent response.
        
        Args:
            goal_id: Goal identifier
            plan_response: Response from planning agent
        """
        plan_data = {
            "planning_agent_id": plan_response.get("planning_agent_id", "unknown"),
            "steps": plan_response.get("steps", []),
            "effort_estimate": plan_response.get("effort_estimate"),
            "dependencies": plan_response.get("dependencies", []),
            "risks": plan_response.get("risks", []),
            "rationale": plan_response.get("rationale", ""),
        }
        
        try:
            self.engine.store_plan(goal_id, plan_data)
        except Exception as e:
            logger.error(f"Failed to store plan for goal {goal_id}: {e}")
    
    def get_plans(self, goal_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all plans for a goal.
        
        Args:
            goal_id: Goal identifier
        
        Returns:
            Dictionary of plans
        """
        context = self.engine.get_context(goal_id)
        if not context:
            return {}
        
        return context.plans
    
    def has_plans(self, goal_id: str) -> bool:
        """Check if plans exist for a goal."""
        context = self.engine.get_context(goal_id)
        if not context:
            return False
        return len(context.plans) > 0
    
    def transition_to_review(self, goal_id: str) -> bool:
        """Transition goal to plan review state."""
        return self.engine.transition_to_review(goal_id)
