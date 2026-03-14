"""
Central configuration loaded from environment variables / .env file.

Usage:
    from config import settings
    settings.moorcheh_api_key
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Moorcheh ──────────────────────────────────────────────────────────────
    moorcheh_api_key: str = Field(
        default="",
        description="Moorcheh API key — set via MOORCHEH_API_KEY env var or .env file",
    )
    moorcheh_base_url: str = Field(
        "https://api.moorcheh.ai/v1", description="Moorcheh base URL"
    )

    # ── Project Identity ──────────────────────────────────────────────────────
    project_id: str = Field("my-project", description="Unique project identifier")
    default_workspace_id: str = Field(
        "main", description="Default workspace/branch name"
    )

    # ── LLM Summarizer ────────────────────────────────────────────────────────
    summarizer_provider: str = Field(
        "openai",
        description="LLM provider for compaction summaries: openai | anthropic | rule_based",
    )
    openai_api_key: str = Field("", description="OpenAI API key")
    openai_model: str = Field("gpt-4o-mini", description="OpenAI model name")
    anthropic_api_key: str = Field("", description="Anthropic API key")
    anthropic_model: str = Field(
        "claude-3-haiku-20240307", description="Anthropic model name"
    )

    # ── Compaction ────────────────────────────────────────────────────────────
    compaction_trigger_count: int = Field(
        50, description="Number of events before triggering compaction"
    )
    compaction_max_importance: int = Field(
        3,
        description="Records with importance <= this are eligible for compaction",
    )

    # ── API Server ────────────────────────────────────────────────────────────
    api_host: str = Field("0.0.0.0", description="FastAPI bind host")
    api_port: int = Field(8000, description="FastAPI bind port")
    api_log_level: str = Field("info", description="Uvicorn log level")

    # ── SQLite ────────────────────────────────────────────────────────────────
    sqlite_path: str = Field(
        "./data/spm_index.db", description="Path to SQLite index database"
    )

    # ── Fallback ──────────────────────────────────────────────────────────────
    fallback_json_path: str = Field(
        "./data/fallback_store.json", description="Path to offline JSON fallback store"
    )

    # ── Conflict Thresholds ───────────────────────────────────────────────────
    conflict_block_threshold: float = Field(
        0.7, description="Composite risk score threshold for blocking a claim"
    )
    conflict_warn_threshold: float = Field(
        0.4, description="Composite risk score threshold for issuing a warning"
    )
    semantic_similarity_threshold: float = Field(
        0.75,
        description="Moorcheh similarity score above which two intents are considered overlapping",
    )

    # ── Retrieval Budget ──────────────────────────────────────────────────────
    retrieval_top_k: int = Field(
        5, description="Maximum documents returned per similarity search"
    )


settings = Settings()
