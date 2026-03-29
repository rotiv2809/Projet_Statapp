import pytest

from app.llm.factory import LLMConfigurationError, load_llm_settings


def test_load_llm_settings_requires_openai_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMConfigurationError) as exc:
        load_llm_settings()

    assert "OPENAI_API_KEY" in str(exc.value)


def test_load_llm_settings_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")

    with pytest.raises(LLMConfigurationError) as exc:
        load_llm_settings()

    assert "unknown LLM_PROVIDER" in str(exc.value)


def test_load_llm_settings_rejects_invalid_temperature(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1")
    monkeypatch.setenv("LLM_TEMPERATURE", "fast")

    with pytest.raises(LLMConfigurationError) as exc:
        load_llm_settings()

    assert "LLM_TEMPERATURE must be a number" in str(exc.value)
