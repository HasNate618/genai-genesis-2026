"""Configuration bootstrap for Moorcheh-backed orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


DEFAULT_MOORCHEH_BASE_URL = "https://api.moorcheh.ai/v1"
DEFAULT_VECTOR_NAMESPACE = "workflow-context-vectors"
DEFAULT_VECTOR_DIMENSION = 1536


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


def _env(name: str, *, required: bool = False, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value or ""


def _env_int(name: str, *, default: int) -> int:
    raw = _env(name, default=str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer.") from exc
    if value <= 0:
        raise ConfigError(f"Environment variable {name} must be > 0.")
    return value


def _env_float(name: str, *, default: float, min_value: float, max_value: float) -> float:
    raw = _env(name, default=str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be a float.") from exc
    if not (min_value <= value <= max_value):
        raise ConfigError(
            f"Environment variable {name} must be between {min_value} and {max_value}."
        )
    return value


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    moorcheh_api_key: str
    moorcheh_base_url: str
    moorcheh_vector_namespace: str
    moorcheh_vector_dimension: int
    embedding_provider: str
    embedding_model: str
    embedding_api_key: str
    embedding_base_url: str
    embedding_batch_size: int
    retrieval_top_k: int
    conflict_threshold: float
    max_context_window: int

    @classmethod
    def from_env(cls) -> "Settings":
        provider = _env("EMBEDDING_PROVIDER", default="openai").lower()
        embedding_api_key = _env("EMBEDDING_API_KEY", default="")
        if provider != "mock" and not embedding_api_key:
            raise ConfigError(
                "EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER is not 'mock'."
            )

        return cls(
            moorcheh_api_key=_env("MOORCHEH_API_KEY", required=True),
            moorcheh_base_url=_env("MOORCHEH_BASE_URL", default=DEFAULT_MOORCHEH_BASE_URL),
            moorcheh_vector_namespace=_env(
                "MOORCHEH_VECTOR_NAMESPACE", default=DEFAULT_VECTOR_NAMESPACE
            ),
            moorcheh_vector_dimension=_env_int(
                "MOORCHEH_VECTOR_DIMENSION", default=DEFAULT_VECTOR_DIMENSION
            ),
            embedding_provider=provider,
            embedding_model=_env("EMBEDDING_MODEL", default="text-embedding-3-small"),
            embedding_api_key=embedding_api_key,
            embedding_base_url=_env("EMBEDDING_BASE_URL", default=""),
            embedding_batch_size=_env_int("EMBEDDING_BATCH_SIZE", default=32),
            retrieval_top_k=_env_int("CONTEXT_RETRIEVAL_TOP_K", default=12),
            conflict_threshold=_env_float(
                "CONFLICT_THRESHOLD", default=0.35, min_value=0.0, max_value=1.0
            ),
            max_context_window=_env_int("MAX_CONTEXT_WINDOW", default=40),
        )

    def redacted(self) -> dict[str, str | int | float]:
        """Returns a safe representation for logs and diagnostics."""
        return {
            "moorcheh_base_url": self.moorcheh_base_url,
            "moorcheh_vector_namespace": self.moorcheh_vector_namespace,
            "moorcheh_vector_dimension": self.moorcheh_vector_dimension,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_base_url": self.embedding_base_url or "(default)",
            "embedding_batch_size": self.embedding_batch_size,
            "retrieval_top_k": self.retrieval_top_k,
            "conflict_threshold": self.conflict_threshold,
            "max_context_window": self.max_context_window,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache runtime settings."""
    return Settings.from_env()


def reset_settings_cache() -> None:
    """Clear cached settings, primarily for tests."""
    get_settings.cache_clear()

