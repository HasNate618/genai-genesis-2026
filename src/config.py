from pydantic_settings import BaseSettings
from typing import Literal
import os


class Settings(BaseSettings):
    # Moorcheh Configuration
    moorcheh_api_key: str = "test-key"
    moorcheh_base_url: str = "https://api.moorcheh.ai"
    project_id: str = "default-project"
    
    # Environment
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    
    # Orchestration
    orchestration_max_planning_wait_seconds: int = 60
    orchestration_enable_auto_approval: bool = False
    orchestration_task_assignment_strategy: Literal["round_robin", "skill_based", "random"] = "round_robin"
    orchestration_agent_webhook_base_url: str = "http://localhost:8001"
    
    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
