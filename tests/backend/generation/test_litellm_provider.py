"""Tests for the LiteLLM provider adapter used by generation."""

import asyncio
import sys
import types

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
        model="openai/gpt-4o-mini",
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
