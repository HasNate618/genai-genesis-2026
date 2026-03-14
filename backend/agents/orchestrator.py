from typing import Dict, Any, List
import os
import uuid
from agents.base import PlannerAgent, CoordinatorAgent, CoderAgent, MergerAgent, QATesterAgent
from memory.semantic_store import memory_store
from core.config import config

class WorkflowOrchestrator:
    def __init__(self):
        self.planner = PlannerAgent()
        self.coordinator = CoordinatorAgent()
        self.coder_agents: List[CoderAgent] = []
        self.merger = MergerAgent()
        self.qa_tester = QATesterAgent()
        
    def initialize_coder_agents(self, workflow_id: str, count: int = 3):
        workspace = config.WORKSPACE_DIR
        os.makedirs(workspace, exist_ok=True)
        
        self.coder_agents = []
        for i in range(count):
            agent_dir = os.path.join(workspace, f"workflow_{workflow_id}", f"agent_{i+1}")
            os.makedirs(agent_dir, exist_ok=True)
            agent = CoderAgent(agent_id=f"coder_{i+1}", isolation_dir=agent_dir)
            self.coder_agents.append(agent)
    
    def run_step1_goal(self, project_id: str, goal: str) -> Dict[str, Any]:
        workflow = memory_store.create_workflow(project_id, goal)
        return {"workflow_id": workflow["id"], "status": workflow["status"]}
    
    def run_step2_planning(self, workflow_id: str) -> Dict[str, Any]:
        workflow = memory_store.get_workflow(workflow_id)
        if not workflow:
            return {"error": "Workflow not found"}
        
        context = {"goal": workflow["goal"]}
        result = self.planner.run(context)
        
        memory_store.update_workflow(workflow_id, status="planning")
        memory_store.store_agent_output(workflow_id, "planner", result)
        
        plans_text = result.get("plans", "")
        plan_lines = [line.strip() for line in plans_text.split("\n") if line.strip()]
        
        for plan_desc in plan_lines:
            memory_store.create_plan(workflow_id, plan_desc)
        
        return {
            "workflow_id": workflow_id,
            "plans": plan_lines,
            "status": "awaiting_approval"
        }
    
    def run_step4_coordinating(self, workflow_id: str) -> Dict[str, Any]:
        workflow = memory_store.get_workflow(workflow_id)
        plans = workflow.get("plans", [])
        
        context = {
            "goal": workflow["goal"],
            "plans": "\n".join(plans)
        }
        result = self.coordinator.run(context)
        
        memory_store.update_workflow(workflow_id, status="coordinating", tasks=result.get("tasks", ""))
        memory_store.store_agent_output(workflow_id, "coordinator", result)
        
        return {
            "workflow_id": workflow_id,
            "tasks": result.get("tasks", ""),
            "status": "ready_for_coding"
        }
    
    def run_step6_coding(self, workflow_id: str, tasks: List[str]) -> Dict[str, Any]:
        memory_store.update_workflow(workflow_id, status="coding")
        self.initialize_coder_agents(workflow_id, config.MAX_CODER_AGENTS)
        
        results = []
        for i, task in enumerate(tasks[:len(self.coder_agents)]):
            agent = self.coder_agents[i]
            context = {"task": task}
            result = agent.run(context)
            results.append(result)
            memory_store.store_agent_output(workflow_id, f"coder_{i+1}", result)
        
        return {
            "workflow_id": workflow_id,
            "coder_outputs": results,
            "status": "ready_for_merging"
        }
    
    def run_step7_merging(self, workflow_id: str, coder_outputs: List[Dict]) -> Dict[str, Any]:
        memory_store.update_workflow(workflow_id, status="merging")
        
        context = {"coder_outputs": coder_outputs}
        result = self.merger.run(context)
        
        memory_store.store_agent_output(workflow_id, "merger", result)
        
        return {
            "workflow_id": workflow_id,
            "merged_code": result.get("merged_output", ""),
            "status": "ready_for_testing"
        }
    
    def run_step8_testing(self, workflow_id: str, merged_code: str) -> Dict[str, Any]:
        memory_store.update_workflow(workflow_id, status="testing")
        
        context = {"merged_code": merged_code}
        result = self.qa_tester.run(context)
        
        memory_store.store_agent_output(workflow_id, "qa_tester", result)
        
        success = "success" in result.get("test_result", "").lower()
        final_status = "completed" if success else "failed"
        
        memory_store.update_workflow(workflow_id, status=final_status)
        
        return {
            "workflow_id": workflow_id,
            "test_result": result.get("test_result", ""),
            "status": final_status
        }

orchestrator = WorkflowOrchestrator()
