"""Tests for the LiteLLM provider adapter used by generation."""

import asyncio
import sys
import types

import pytest

from agentic_paper_explorer.configs.settings import get_settings


def test_litellm_provider_calls_model_with_prompt(monkeypatch):
    fake_module = types.ModuleType("litellm")

    async def fake_acompletion(**kwargs):
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="Provider result from LiteLLM")
                )
            ]
        )

    fake_module.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider

    provider = LiteLLMProvider(
        model="openrouter/meta-llama/llama-3.2-3b-instruct:free",
        api_base="http://localhost:4000",
        api_key="test-key",
        temperature=0.3,
    )

    response = asyncio.run(
        provider.generate(
            prompt="Explain retrieval.",
            system_prompt="Use the paper context only.",
        )
    )

    assert response == "Provider result from LiteLLM"


def test_litellm_provider_uses_settings_defaults(monkeypatch):
    settings = get_settings()
    fake_module = types.ModuleType("litellm")

    async def fake_acompletion(**kwargs):
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="Default model response")
                )
            ]
        )

    fake_module.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider

    provider = LiteLLMProvider(
        model=settings.llm_model_name,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
    )

    response = asyncio.run(provider.generate(prompt="What is retrieval?"))

    assert response == "Default model response"


def test_litellm_provider_retries_rate_limits_with_exponential_backoff(monkeypatch):
    fake_module = types.ModuleType("litellm")
    calls = 0
    delays: list[float] = []

    class RateLimitError(Exception):
        status_code = 429

    async def fake_acompletion(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RateLimitError("too many requests")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))]
        )

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    fake_module.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider

    provider = LiteLLMProvider(
        model="test-model",
        api_base="http://localhost:4000",
        api_key="test-key",
        max_retries=2,
        retry_backoff_seconds=0.25,
    )

    assert asyncio.run(provider.generate(prompt="retry me")) == "ok"
    assert calls == 3
    assert delays == [0.25, 0.5]


def test_litellm_provider_does_not_retry_non_transient_errors(monkeypatch):
    fake_module = types.ModuleType("litellm")
    calls = 0

    class BadRequestError(Exception):
        status_code = 400

    async def fake_acompletion(**kwargs):
        nonlocal calls
        calls += 1
        raise BadRequestError("invalid request")

    fake_module.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider, ProviderError

    provider = LiteLLMProvider(
        model="test-model",
        api_base="http://localhost:4000",
        api_key="test-key",
    )

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.generate(prompt="bad request"))

    assert error.value.category == "provider"
    assert error.value.retryable is False
    assert calls == 1


def test_litellm_provider_maps_timeout(monkeypatch):
    fake_module = types.ModuleType("litellm")

    async def fake_acompletion(**kwargs):
        raise asyncio.TimeoutError()

    fake_module.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider, ProviderError

    provider = LiteLLMProvider(
        model="test-model",
        api_base="http://localhost:4000",
        api_key="test-key",
        max_retries=0,
    )

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.generate(prompt="slow request"))

    assert error.value.category == "timeout"
    assert error.value.retryable is True


def test_litellm_provider_retries_server_and_network_errors(monkeypatch):
    fake_module = types.ModuleType("litellm")
    calls = 0

    class ServerError(Exception):
        status_code = 503

    async def fake_acompletion(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ServerError("gateway unavailable")
        if calls == 2:
            raise ConnectionError("connection reset")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="recovered"))]
        )

    async def fake_sleep(delay: float) -> None:
        return None

    fake_module.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider

    provider = LiteLLMProvider(
        model="test-model",
        api_base="http://localhost:4000",
        api_key="test-key",
        max_retries=2,
    )

    assert asyncio.run(provider.generate(prompt="recover me")) == "recovered"
    assert calls == 3


def test_litellm_provider_streams_partial_deltas(monkeypatch):
    fake_module = types.ModuleType("litellm")
    calls: list[dict[str, object]] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)

        async def response_stream():
            for text in ("Grounded ", "answer [1]."):
                yield types.SimpleNamespace(
                    choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text))]
                )

        return response_stream()

    fake_module.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider

    provider = LiteLLMProvider(
        model="test-model",
        api_base="http://localhost:4000",
        api_key="test-key",
    )

    async def collect() -> list[str]:
        return [delta async for delta in provider.generate_stream(prompt="stream me")]

    assert asyncio.run(collect()) == ["Grounded ", "answer [1]."]
    assert calls[0]["stream"] is True
