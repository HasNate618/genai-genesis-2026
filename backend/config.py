"""Configuration bootstrap for Moorcheh-backed orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_MOORCHEH_BASE_URL = "https://api.moorcheh.ai/v1"
DEFAULT_VECTOR_NAMESPACE = "workflow-context-vectors"
DEFAULT_VECTOR_DIMENSION = 1536
DEFAULT_COHERE_VECTOR_DIMENSION = 1024
DEFAULT_LLM_BASE_URL = "https://qyt7893blb71b5d3.us-east-2.aws.endpoints.huggingface.cloud/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


@lru_cache(maxsize=8)
def _dotenv_values(cwd: str) -> dict[str, str]:
    values: dict[str, str] = {}
    cwd_path = Path(cwd).resolve()
    project_root = Path(__file__).resolve().parents[1]
    candidates = [cwd_path / ".env"]
    if project_root == cwd_path or project_root in cwd_path.parents:
        candidates.append(project_root / ".env")
    for path in candidates:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if value and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key] = value
        if values:
            return values
    return values


def _normalize_embedding_provider(
    raw_provider: str, *, embedding_key: str, cohere_key: str
) -> str:
    provider = raw_provider.strip().lower()
    aliases = {"ochere": "cohere"}
    if provider in aliases:
        provider = aliases[provider]
    supported = {"mock", "openai", "cohere"}
    if provider in supported:
        return provider
    if provider.startswith("http://") or provider.startswith("https://"):
        if cohere_key:
            return "cohere"
        if embedding_key:
            return "openai"
        raise ConfigError(
            "EMBEDDING_PROVIDER looks like a URL. Set EMBEDDING_PROVIDER to one of: "
            "mock, openai, cohere."
        )
    raise ConfigError(
        f"Unsupported EMBEDDING_PROVIDER '{raw_provider}'. "
        "Supported providers: mock, openai, cohere."
    )


def _resolve_vector_dimension(*, provider: str, embedding_model: str) -> int:
    raw_dimension = _raw_env("MOORCHEH_VECTOR_DIMENSION").strip()
    if not raw_dimension:
        return DEFAULT_COHERE_VECTOR_DIMENSION if provider == "cohere" else DEFAULT_VECTOR_DIMENSION
    try:
        resolved = int(raw_dimension)
    except ValueError as exc:
        raise ConfigError("Environment variable MOORCHEH_VECTOR_DIMENSION must be an integer.") from exc
    if resolved <= 0:
        raise ConfigError("Environment variable MOORCHEH_VECTOR_DIMENSION must be > 0.")

    if provider == "cohere":
        known_model_dims = {
            "embed-english-v3.0": DEFAULT_COHERE_VECTOR_DIMENSION,
            "embed-multilingual-v3.0": DEFAULT_COHERE_VECTOR_DIMENSION,
        }
        expected = known_model_dims.get(embedding_model.strip().lower())
        if expected is not None and resolved != expected:
            if resolved == DEFAULT_VECTOR_DIMENSION:
                return expected
            raise ConfigError(
                f"MOORCHEH_VECTOR_DIMENSION={resolved} does not match EMBEDDING_MODEL "
                f"'{embedding_model}' (expected {expected})."
            )
    return resolved


def _resolve_vector_namespace(*, provider: str, vector_dimension: int) -> str:
    raw_namespace = _raw_env("MOORCHEH_VECTOR_NAMESPACE").strip()
    cohere_default_namespace = f"{DEFAULT_VECTOR_NAMESPACE}-{DEFAULT_COHERE_VECTOR_DIMENSION}"
    if not raw_namespace:
        if provider == "cohere" and vector_dimension == DEFAULT_COHERE_VECTOR_DIMENSION:
            return cohere_default_namespace
        return DEFAULT_VECTOR_NAMESPACE
    if (
        provider == "cohere"
        and vector_dimension == DEFAULT_COHERE_VECTOR_DIMENSION
        and raw_namespace == DEFAULT_VECTOR_NAMESPACE
    ):
        return cohere_default_namespace
    return raw_namespace


def _env(name: str, *, required: bool = False, default: str | None = None) -> str:
    value = os.getenv(name, "")
    if not value:
        value = _dotenv_values(str(Path.cwd())).get(name, "")
    if not value and default is not None:
        value = default
    if required and not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value or ""


def _raw_env(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    return _dotenv_values(str(Path.cwd())).get(name, "")


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
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_api_key: str = ""
    llm_call_timeout_seconds: int = 180

    @classmethod
    def from_env(
        cls,
        *,
        moorcheh_api_key: str | None = None,
        embedding_provider: str | None = None,
        embedding_api_key: str | None = None,
        llm_api_key: str | None = None,
    ) -> "Settings":
        raw_provider = embedding_provider or _env("EMBEDDING_PROVIDER", default="mock")
        env_embedding_key = _env("EMBEDDING_API_KEY", default="")
        cohere_key = _env("COHERE_API_KEY", default="")
        provider = _normalize_embedding_provider(
            raw_provider, embedding_key=env_embedding_key, cohere_key=cohere_key
        )
        if embedding_api_key is not None:
            resolved_embedding_key = embedding_api_key
        elif provider == "cohere":
            resolved_embedding_key = cohere_key or env_embedding_key
        else:
            resolved_embedding_key = env_embedding_key
        resolved_llm_key = llm_api_key if llm_api_key is not None else _env("LLM_API_KEY", default="")
        if provider != "mock" and not resolved_embedding_key:
            raise ConfigError(
                "Embedding API key is required when EMBEDDING_PROVIDER is not 'mock'. "
                "Set EMBEDDING_API_KEY, or COHERE_API_KEY when EMBEDDING_PROVIDER='cohere'."
            )
        default_embedding_model = (
            "embed-english-v3.0" if provider == "cohere" else "text-embedding-3-small"
        )
        resolved_embedding_model = _env("EMBEDDING_MODEL", default=default_embedding_model)
        resolved_vector_dimension = _resolve_vector_dimension(
            provider=provider, embedding_model=resolved_embedding_model
        )
        resolved_vector_namespace = _resolve_vector_namespace(
            provider=provider, vector_dimension=resolved_vector_dimension
        )

        return cls(
            moorcheh_api_key=moorcheh_api_key or _env("MOORCHEH_API_KEY", required=True),
            moorcheh_base_url=_env("MOORCHEH_BASE_URL", default=DEFAULT_MOORCHEH_BASE_URL),
            moorcheh_vector_namespace=resolved_vector_namespace,
            moorcheh_vector_dimension=resolved_vector_dimension,
            embedding_provider=provider,
            embedding_model=resolved_embedding_model,
            embedding_api_key=resolved_embedding_key,
            embedding_base_url=_env("EMBEDDING_BASE_URL", default=""),
            embedding_batch_size=_env_int("EMBEDDING_BATCH_SIZE", default=32),
            retrieval_top_k=_env_int("CONTEXT_RETRIEVAL_TOP_K", default=12),
            conflict_threshold=_env_float(
                "CONFLICT_THRESHOLD", default=0.35, min_value=0.0, max_value=1.0
            ),
            max_context_window=_env_int("MAX_CONTEXT_WINDOW", default=40),
            llm_base_url=_env("LLM_BASE_URL", default=DEFAULT_LLM_BASE_URL),
            llm_model=_env("LLM_MODEL", default=DEFAULT_LLM_MODEL),
            llm_api_key=resolved_llm_key,
            llm_call_timeout_seconds=_env_int("LLM_CALL_TIMEOUT_SECONDS", default=180),
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
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_api_key": "(set)" if self.llm_api_key else "(not set)",
            "llm_call_timeout_seconds": self.llm_call_timeout_seconds,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache runtime settings."""
    return Settings.from_env()


def reset_settings_cache() -> None:
    """Clear cached settings, primarily for tests."""
    get_settings.cache_clear()
    _dotenv_values.cache_clear()
