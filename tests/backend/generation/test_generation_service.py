"""Tests for prompt assembly and the generation service layer."""

import asyncio

from agentic_paper_explorer.backend.generation.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    INSUFFICIENT_CONTEXT_MESSAGE,
)
from agentic_paper_explorer.backend.generation.provider import ProviderError
from agentic_paper_explorer.backend.generation.service import GenerationResult, GenerationService
from agentic_paper_explorer.backend.retrieval.service import RetrievedChunk


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
            }
        )
        return "This paper explains retrieval in a modern RAG pipeline."


class FailingProvider:
    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        raise ProviderError("rate limited", category="rate_limit", retryable=True)


def test_generation_service_uses_detailed_default_system_prompt() -> None:
    service = GenerationService(provider=FakeProvider())

    assert "Use only claims supported by the supplied context" in service._system_prompt
    assert "Cite every material claim" in service._system_prompt
    assert service._system_prompt == DEFAULT_SYSTEM_PROMPT


def test_generation_service_builds_prompt_from_chunks() -> None:
    service = GenerationService(provider=FakeProvider())
    chunks = [
        RetrievedChunk(
            paper_id="paper-1",
            title="Retrieval Overview",
            text="This paper explains retrieval in a RAG pipeline.",
            score=0.9,
            source_url="https://arxiv.org/abs/paper-1",
        )
    ]

    prompt = service.build_prompt("What is retrieval?", chunks)

    assert "What is retrieval?" in prompt
    assert "Retrieval Overview" in prompt
    assert "This paper explains retrieval in a RAG pipeline." in prompt
    assert "numbered paper excerpts" in prompt
    assert "[1] Retrieval Overview" in prompt
    assert "[1]" in prompt


def test_generation_service_orders_chunks_by_score_and_deduplicates_sources() -> None:
    service = GenerationService(provider=FakeProvider())
    chunks = [
        RetrievedChunk(
            paper_id="paper-low",
            title="Lower ranked",
            text="Lower-ranked excerpt.",
            score=0.4,
            source_url="https://arxiv.org/abs/paper-1",
        ),
        RetrievedChunk(
            paper_id="paper-high",
            title="Highest ranked",
            text="Highest-ranked excerpt.",
            score=0.9,
            source_url="https://arxiv.org/abs/paper-1",
        ),
    ]

    prompt = service.build_prompt("Which excerpt matters most?", chunks)

    assert prompt.index("[1] Highest ranked") < prompt.index("[2] Lower ranked")

    result = asyncio.run(service.answer_question("Which excerpt matters most?", chunks))

    assert result.sources == ["https://arxiv.org/abs/paper-1"]


def test_generation_service_abstains_without_usable_context() -> None:
    provider = FakeProvider()
    service = GenerationService(provider=provider, model="test-model")
    chunks = [
        RetrievedChunk(
            paper_id="paper-empty",
            title="Empty excerpt",
            text="   ",
            score=0.95,
            source_url="https://arxiv.org/abs/paper-empty",
        )
    ]

    result = asyncio.run(service.answer_question("What does it say?", chunks))

    assert result.answer == INSUFFICIENT_CONTEXT_MESSAGE
    assert result.sources == ["https://arxiv.org/abs/paper-empty"]
    assert result.model == "test-model"
    assert provider.calls == []


def test_generation_service_returns_structured_answer() -> None:
    provider = FakeProvider()
    service = GenerationService(provider=provider)
    chunks = [
        RetrievedChunk(
            paper_id="paper-2",
            title="RAG Systems",
            text="RAG combines retrieval with generation.",
            score=0.85,
            source_url="https://arxiv.org/abs/paper-2",
        )
    ]

    result = asyncio.run(service.generate("How do RAG systems work?", chunks))

    assert isinstance(result, GenerationResult)
    assert result.answer.startswith("This paper")
    assert result.sources == ["https://arxiv.org/abs/paper-2"]
    assert provider.calls


def test_generation_service_returns_fallback_when_provider_fails() -> None:
    service = GenerationService(provider=FailingProvider(), model="test-model")
    chunks = [
        RetrievedChunk(
            paper_id="paper-3",
            title="Reliable Generation",
            text="Generation can fail transiently.",
            score=0.8,
            source_url="https://arxiv.org/abs/paper-3",
        )
    ]

    result = asyncio.run(service.answer_question("What can fail?", chunks))

    assert result.answer.startswith("I could not generate an answer")
    assert result.sources == ["https://arxiv.org/abs/paper-3"]
    assert result.model == "test-model"
