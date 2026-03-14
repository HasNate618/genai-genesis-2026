import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.0-pro-exp-02-05"
    MOORCHEH_API_KEY: str = os.getenv("MOORCHEH_API_KEY", "")
    WORKSPACE_DIR: str = os.getenv("WORKSPACE_DIR", "./workspace")
    MAX_CODER_AGENTS: int = 3
    CONFLICT_THRESHOLD: float = 0.20
    
config = Config()
