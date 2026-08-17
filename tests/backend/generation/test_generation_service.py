"""Tests for prompt assembly and the generation service layer."""

import asyncio
from collections.abc import AsyncIterator

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

    async def generate_stream(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        yield "This paper explains retrieval in a modern RAG pipeline."


class FailingProvider:
    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        raise ProviderError("rate limited", category="rate_limit", retryable=True)

    def generate_stream(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        raise ProviderError("rate limited", category="rate_limit", retryable=True)


class StreamingProvider:
    def __init__(self, deltas: list[str]) -> None:
        self.deltas = deltas
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        return "".join(self.deltas)

    async def generate_stream(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        for delta in self.deltas:
            yield delta


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


def test_generation_service_streams_partial_output_and_completion_metadata() -> None:
    provider = StreamingProvider(["Grounded ", "answer [1]."])
    service = GenerationService(provider=provider, model="test-model")
    chunks = [
        RetrievedChunk(
            paper_id="paper-stream",
            title="Streaming Generation",
            text="Streaming returns partial output.",
            score=0.9,
            source_url="https://arxiv.org/abs/paper-stream",
        )
    ]

    async def collect():
        return [event async for event in service.stream_answer("What happens?", chunks)]

    events = asyncio.run(collect())

    assert [(event.event, event.data) for event in events] == [
        ("chunk", {"text": "Grounded "}),
        ("chunk", {"text": "answer [1]."}),
        (
            "complete",
            {
                "sources": ["https://arxiv.org/abs/paper-stream"],
                "model": "test-model",
                "degraded": False,
                "error_category": None,
            },
        ),
    ]
    assert provider.calls


def test_generation_service_stream_abstains_without_context() -> None:
    provider = StreamingProvider(["should not be used"])
    service = GenerationService(provider=provider)

    async def collect():
        return [
            event
            async for event in service.stream_answer(
                "What happens?",
                [
                    RetrievedChunk(
                        paper_id="paper-empty",
                        title="Empty",
                        text="",
                        score=0.9,
                    )
                ],
            )
        ]

    events = asyncio.run(collect())

    assert events[0].data["text"].startswith("I do not have enough")
    assert events[-1].event == "complete"
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


def test_generation_service_marks_provider_failure_as_degraded() -> None:
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

    assert result.degraded is True
    assert result.error_category == "rate_limit"


def test_generation_service_answer_is_not_degraded_on_success() -> None:
    service = GenerationService(provider=FakeProvider(), model="test-model")
    chunks = [
        RetrievedChunk(
            paper_id="paper-4",
            title="Working Generation",
            text="Generation can succeed.",
            score=0.8,
            source_url="https://arxiv.org/abs/paper-4",
        )
    ]

    result = asyncio.run(service.answer_question("What works?", chunks))

    assert result.degraded is False
    assert result.error_category is None


def test_generation_service_abstention_is_not_marked_degraded() -> None:
    service = GenerationService(provider=FakeProvider(), model="test-model")
    chunks = [
        RetrievedChunk(paper_id="paper-empty", title="Empty", text="  ", score=0.9),
    ]

    result = asyncio.run(service.answer_question("What does it say?", chunks))

    assert result.degraded is False
    assert result.error_category is None


def test_generation_service_stream_emits_error_event_when_provider_fails() -> None:
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

    async def collect():
        return [event async for event in service.stream_answer("What can fail?", chunks)]

    events = asyncio.run(collect())

    assert [event.event for event in events] == ["error", "complete"]
    assert events[0].data["category"] == "rate_limit"
    assert events[-1].data["degraded"] is True
    assert events[-1].data["error_category"] == "rate_limit"
