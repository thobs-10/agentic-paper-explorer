"""Tests for environment-driven settings."""

import pytest

from agentic_paper_explorer.configs.settings import Settings, get_settings


def test_settings_defaults_when_no_env_vars_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ALLOWED_ORIGINS",
        "ARXIV_BASE_URL",
        "ARXIV_TIMEOUT_SECONDS",
        "ARXIV_MAX_RETRIES",
        "ARXIV_RETRY_BACKOFF_SECONDS",
        "ARXIV_MIN_REQUEST_INTERVAL_SECONDS",
        "LITELLM_API_BASE",
        "LITELLM_API_KEY",
        "LITELLM_MODEL_NAME",
        "LITELLM_TEMPERATURE",
        "LITELLM_MAX_TOKENS",
        "LLM_API_BASE",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "LITELLM_TIMEOUT_SECONDS",
        "LITELLM_MAX_RETRIES",
        "LITELLM_RETRY_BACKOFF_SECONDS",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "LLM_RETRY_BACKOFF_SECONDS",
        "BACKEND_API_BASE_URL",
        "REDIS_URL",
        "QDRANT_URL",
        "RETRIEVAL_TOP_K",
        "RETRIEVAL_SCORE_THRESHOLD",
        "RETRIEVAL_CACHE_TTL_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == ["http://localhost:8501"]
    assert settings.arxiv_base_url == "https://export.arxiv.org/api/query"
    assert settings.arxiv_timeout_seconds == 15.0
    assert settings.arxiv_max_retries == 3
    assert settings.arxiv_retry_backoff_seconds == 1.0
    assert settings.arxiv_min_request_interval_seconds == 3.0
    assert settings.backend_api_base_url == "http://localhost:8000"
    assert settings.llm_api_base == "http://localhost:4000"
    assert settings.llm_api_key == ""
    assert settings.llm_model_name == "openrouter/google/gemma-4-26b-a4b-it:free"
    assert settings.llm_temperature == 0.2
    assert settings.llm_max_tokens == 512
    assert settings.llm_timeout_seconds == 30.0
    assert settings.llm_max_retries == 2
    assert settings.llm_retry_backoff_seconds == 0.5
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.retrieval_top_k == 5
    assert settings.retrieval_score_threshold == 0.2
    assert settings.retrieval_cache_ttl_seconds == 3600


def test_settings_parses_comma_separated_allowed_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.test, https://b.test")

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == ["https://a.test", "https://b.test"]


def test_settings_reads_litellm_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_API_BASE", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    monkeypatch.setenv("LITELLM_MODEL_NAME", "openrouter/meta-llama/llama-3.2-3b-instruct:free")
    monkeypatch.setenv("LITELLM_TEMPERATURE", "0.5")
    monkeypatch.setenv("LITELLM_MAX_TOKENS", "1024")
    monkeypatch.setenv("LITELLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("LITELLM_MAX_RETRIES", "4")
    monkeypatch.setenv("LITELLM_RETRY_BACKOFF_SECONDS", "1.25")

    settings = Settings(_env_file=None)

    assert settings.llm_api_base == "http://litellm:4000"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_model_name == "openrouter/meta-llama/llama-3.2-3b-instruct:free"
    assert settings.llm_temperature == 0.5
    assert settings.llm_max_tokens == 1024
    assert settings.llm_timeout_seconds == 45.0
    assert settings.llm_max_retries == 4
    assert settings.llm_retry_backoff_seconds == 1.25


def test_settings_accepts_list_value_for_allowed_origins() -> None:
    settings = Settings(_env_file=None, allowed_origins=["https://a.test"])

    assert settings.allowed_origins == ["https://a.test"]


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second
