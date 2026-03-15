from pathlib import Path

import pytest

from backend.config import ConfigError, Settings, reset_settings_cache


def test_config_requires_moorcheh_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.delenv("MOORCHEH_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_config_requires_embedding_key_for_non_mock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_config_accepts_cohere_api_key_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "cohere")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    settings = Settings.from_env()
    assert settings.embedding_api_key == "cohere-key"
    assert settings.embedding_model == "embed-english-v3.0"


def test_config_accepts_common_provider_typo_ochere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ochere")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    settings = Settings.from_env()
    assert settings.embedding_provider == "cohere"


def test_config_maps_url_provider_to_cohere_when_cohere_key_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv(
        "EMBEDDING_PROVIDER",
        "https://qyt7893blb71b5d3.us-east-2.aws.endpoints.huggingface.cloud/v1",
    )
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    settings = Settings.from_env()
    assert settings.embedding_provider == "cohere"


def test_config_defaults_cohere_dimension_to_1024(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "cohere")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    monkeypatch.delenv("MOORCHEH_VECTOR_DIMENSION", raising=False)
    settings = Settings.from_env()
    assert settings.moorcheh_vector_dimension == 1024


def test_config_cohere_legacy_1536_dimension_autocorrects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "cohere")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    monkeypatch.setenv("MOORCHEH_VECTOR_DIMENSION", "1536")
    settings = Settings.from_env()
    assert settings.moorcheh_vector_dimension == 1024


def test_config_cohere_rejects_mismatched_custom_dimension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "cohere")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    monkeypatch.setenv("MOORCHEH_VECTOR_DIMENSION", "2048")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_config_defaults_hosted_hf_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    settings = Settings.from_env()
    assert settings.llm_base_url == "https://qyt7893blb71b5d3.us-east-2.aws.endpoints.huggingface.cloud/v1"
    assert settings.llm_model == "openai/gpt-oss-120b"


def test_config_reads_cohere_key_from_dotenv_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "MOORCHEH_API_KEY=abc",
                "EMBEDDING_PROVIDER=cohere",
                "COHERE_API_KEY=cohere-key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOORCHEH_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    reset_settings_cache()

    settings = Settings.from_env()

    assert settings.embedding_provider == "cohere"
    assert settings.embedding_api_key == "cohere-key"


def test_config_allows_per_job_llm_key_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    settings = Settings.from_env(llm_api_key="job-key")
    assert settings.llm_api_key == "job-key"
    assert settings.llm_call_timeout_seconds == 180
