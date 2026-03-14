from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime

class MemoryStore:
    def __init__(self):
        self.projects: Dict[str, Dict] = {}
        self.workflows: Dict[str, Dict] = {}
        self.tasks: Dict[str, Dict] = {}
        self.plans: Dict[str, Dict] = {}
        self.agent_outputs: Dict[str, List[Dict]] = {}
    
    def create_project(self, name: str) -> Dict:
        project = {
            "id": str(uuid.uuid4()),
            "name": name,
            "created_at": datetime.now().isoformat(),
            "workflows": []
        }
        self.projects[project["id"]] = project
        return project
    
    def create_workflow(self, project_id: str, goal: str) -> Dict:
        workflow = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "goal": goal,
            "status": "pending",
            "current_step": 1,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "plans": [],
            "tasks": []
        }
        self.workflows[workflow["id"]] = workflow
        if project_id in self.projects:
            self.projects[project_id]["workflows"].append(workflow["id"])
        return workflow
    
    def update_workflow(self, workflow_id: str, **kwargs) -> Dict:
        if workflow_id in self.workflows:
            self.workflows[workflow_id].update(kwargs)
            self.workflows[workflow_id]["updated_at"] = datetime.now().isoformat()
        return self.workflows.get(workflow_id, {})
    
    def create_task(self, workflow_id: str, assigned_agent: str, description: str) -> Dict:
        task = {
            "id": str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "assigned_agent": assigned_agent,
            "description": description,
            "status": "pending",
            "result": None
        }
        self.tasks[task["id"]] = task
        return task
    
    def create_plan(self, workflow_id: str, description: str) -> Dict:
        plan = {
            "id": str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "description": description,
            "approved": False
        }
        self.plans[plan["id"]] = plan
        return plan
    
    def store_agent_output(self, workflow_id: str, agent_role: str, output: Dict):
        key = f"{workflow_id}:{agent_role}"
        if key not in self.agent_outputs:
            self.agent_outputs[key] = []
        self.agent_outputs[key].append({
            "timestamp": datetime.now().isoformat(),
            "output": output
        })
    
    def get_workflow_history(self, workflow_id: str) -> List[Dict]:
        results = []
        for key, outputs in self.agent_outputs.items():
            if key.startswith(workflow_id):
                results.extend(outputs)
        return results
    
    def get_project(self, project_id: str) -> Optional[Dict]:
        return self.projects.get(project_id)
    
    def get_workflow(self, workflow_id: str) -> Optional[Dict]:
        return self.workflows.get(workflow_id)
    
    def get_project_workflows(self, project_id: str) -> List[Dict]:
        project = self.projects.get(project_id)
        if not project:
            return []
        return [self.workflows[wid] for wid in project.get("workflows", []) if wid in self.workflows]

memory_store = MemoryStore()
