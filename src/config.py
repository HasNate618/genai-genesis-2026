from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Moorcheh
    moorcheh_api_key: str = Field(default="", alias="MOORCHEH_API_KEY")
    moorcheh_base_url: str = Field(
        default="https://api.moorcheh.ai/v1", alias="MOORCHEH_BASE_URL"
    )

    # SPM
    spm_project_id: str = Field(default="default-project", alias="SPM_PROJECT_ID")
    spm_log_level: str = Field(default="INFO", alias="SPM_LOG_LEVEL")

    # LLM
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")

    # Compaction
    compaction_threshold: int = Field(default=50, alias="COMPACTION_THRESHOLD")
    compaction_importance_max: int = Field(
        default=3, alias="COMPACTION_IMPORTANCE_MAX"
    )

    # Storage
    sqlite_path: Path = Field(default=Path("data/spm_index.db"), alias="SQLITE_PATH")
    fallback_dir: Path = Field(default=Path("data/fallback"), alias="FALLBACK_DIR")

    # API
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Retrieval
    top_k_search: int = Field(default=5, alias="TOP_K_SEARCH")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
