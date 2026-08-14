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
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == ["http://localhost:8501"]
    assert settings.arxiv_base_url == "https://export.arxiv.org/api/query"
    assert settings.arxiv_timeout_seconds == 15.0
    assert settings.arxiv_max_retries == 3
    assert settings.arxiv_retry_backoff_seconds == 1.0
    assert settings.arxiv_min_request_interval_seconds == 3.0


def test_settings_parses_comma_separated_allowed_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.test, https://b.test")

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == ["https://a.test", "https://b.test"]


def test_settings_accepts_list_value_for_allowed_origins() -> None:
    settings = Settings(_env_file=None, allowed_origins=["https://a.test"])

    assert settings.allowed_origins == ["https://a.test"]


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second
