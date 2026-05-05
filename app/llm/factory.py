from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel


load_dotenv()


class LLMConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    temperature: float


_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "google": "gemini-1.5-flash",
    "ollama": "llama3.1",
}


def _parse_temperature(raw_value: str) -> float:
    try:
        return float(raw_value)
    except ValueError as exc:
        raise LLMConfigurationError(
            "LLM configuration error: LLM_TEMPERATURE must be a number."
        ) from exc


def load_llm_settings() -> LLMSettings:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider not in _DEFAULT_MODELS:
        allowed = ", ".join(sorted(_DEFAULT_MODELS))
        raise LLMConfigurationError(
            "LLM configuration error: unknown LLM_PROVIDER '{}'. Expected one of: {}.".format(
                provider, allowed
            )
        )

    model = os.getenv("LLM_MODEL", _DEFAULT_MODELS[provider]).strip() or _DEFAULT_MODELS[provider]
    temperature = _parse_temperature(os.getenv("LLM_TEMPERATURE", "0"))

    if provider == "openai" and not os.getenv("OPENAI_API_KEY", "").strip():
        raise LLMConfigurationError(
            "LLM configuration error: OPENAI_API_KEY is required when LLM_PROVIDER=openai."
        )
    if provider == "google" and not os.getenv("GOOGLE_API_KEY", "").strip():
        raise LLMConfigurationError(
            "LLM configuration error: GOOGLE_API_KEY is required when LLM_PROVIDER=google."
        )

    return LLMSettings(provider=provider, model=model, temperature=temperature)


def get_llm() -> BaseChatModel:
    settings = load_llm_settings()
    provider = settings.provider
    model = settings.model
    temperature = settings.temperature

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "LLM configuration error: langchain-openai is required when LLM_PROVIDER=openai."
            ) from exc

        return ChatOpenAI(model=model, temperature=temperature)
    if provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "LLM configuration error: langchain-google-genai is required when LLM_PROVIDER=google."
            ) from exc

        return ChatGoogleGenerativeAI(model=model, temperature=temperature)
    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise LLMConfigurationError(
                "LLM configuration error: langchain-ollama is required when LLM_PROVIDER=ollama."
            ) from exc

        return ChatOllama(model=model, temperature=temperature)

    raise LLMConfigurationError("LLM configuration error: unsupported provider '{}'.".format(provider))
