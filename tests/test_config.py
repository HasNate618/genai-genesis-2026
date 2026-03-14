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

