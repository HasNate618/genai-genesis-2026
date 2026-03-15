import pytest

from backend.config import ConfigError, Settings


def test_config_requires_moorcheh_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOORCHEH_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_config_requires_embedding_key_for_non_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_config_defaults_hosted_hf_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    settings = Settings.from_env()
    assert settings.llm_base_url == "https://qyt7893blb71b5d3.us-east-2.aws.endpoints.huggingface.cloud/v1"
    assert settings.llm_model == "openai/gpt-oss-120b"


def test_config_allows_per_job_llm_key_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOORCHEH_API_KEY", "abc")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    settings = Settings.from_env(llm_api_key="job-key")
    assert settings.llm_api_key == "job-key"
    assert settings.llm_call_timeout_seconds == 180
