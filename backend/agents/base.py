from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from core.llm import generate
from core.config import config

class BaseAgent(ABC):
    def __init__(self, role: str, tools: Optional[List[str]] = None):
        self.role = role
        self.tools = tools or []
        self.model = config.GEMINI_MODEL
    
    @abstractmethod
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        pass
    
    def prompt(self, system_prompt: str, user_prompt: str) -> str:
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
        return generate(full_prompt, self.model)

class PlannerAgent(BaseAgent):
    def __init__(self):
        super().__init__("planner")
    
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        goal = context.get("goal", "")
        system_prompt = """You are a Planning Agent. Your role is to analyze the user's goal and propose 
        implementation plans. Generate clear, actionable plans that can be approved by the user.
        Return your plans as a list of steps."""
        
        user_prompt = f"""Analyze this goal and create implementation plans:
        
Goal: {goal}

Provide a detailed plan with numbered steps."""
        
        result = self.prompt(system_prompt, user_prompt)
        
        return {
            "role": self.role,
            "goal": goal,
            "plans": result,
            "status": "completed"
        }

class CoordinatorAgent(BaseAgent):
    def __init__(self):
        super().__init__("coordinator")
    
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        goal = context.get("goal", "")
        plans = context.get("plans", "")
        
        system_prompt = """You are a Task Coordinator Agent. Your role is to break down approved plans 
        into specific tasks that can be assigned to coder agents. Consider file dependencies and 
        assign tasks to minimize conflicts."""
        
        user_prompt = f"""Break down this goal and plan into individual tasks:
        
Goal: {goal}

Plans: {plans}

Provide tasks as a JSON-like structure with: task_id, description, estimated_files."""
        
        result = self.prompt(system_prompt, user_prompt)
        
        return {
            "role": self.role,
            "tasks": result,
            "status": "completed"
        }

class CoderAgent(BaseAgent):
    def __init__(self, agent_id: str, isolation_dir: str):
        super().__init__("coder", tools=["write", "edit", "bash", "read", "grep", "glob"])
        self.agent_id = agent_id
        self.isolation_dir = isolation_dir
    
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        task = context.get("task", "")
        
        system_prompt = f"""You are a Coder Agent. Your role is to write code based on the assigned task.
        You have access to the following tools: {', '.join(self.tools)}.
        Work in your isolated directory: {self.isolation_dir}
        
        Write clean, functional code. Report your changes."""
        
        user_prompt = f"""Complete this task:
        
Task: {task}"""
        
        result = self.prompt(system_prompt, user_prompt)
        
        return {
            "role": self.role,
            "agent_id": self.agent_id,
            "task": task,
            "output": result,
            "status": "completed"
        }

class MergerAgent(BaseAgent):
    def __init__(self):
        super().__init__("merger")
    
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        coder_outputs = context.get("coder_outputs", [])
        
        system_prompt = """You are a Merger Agent. Your role is to combine code from multiple coder agents
        into a coherent result. Handle any conflicts that arise. If merge is too difficult,
        return a status indicating failure."""
        
        user_prompt = f"""Merge these coder outputs:
        
{coder_outputs}"""
        
        result = self.prompt(system_prompt, user_prompt)
        
        return {
            "role": self.role,
            "merged_output": result,
            "status": "completed"
        }

class QATesterAgent(BaseAgent):
    def __init__(self):
        super().__init__("qa_tester")
    
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        merged_code = context.get("merged_code", "")
        
        system_prompt = """You are a QA Tester Agent. Your role is to run demos of the generated code.
        If the demo succeeds, report success. If it fails, report the failure details."""
        
        user_prompt = f"""Test this code by running a demo:
        
{merged_code}"""
        
        result = self.prompt(system_prompt, user_prompt)
        
        return {
            "role": self.role,
            "test_result": result,
            "status": "completed"
        }
