"""Tests for prompt assembly and the generation service layer."""

import asyncio

from agentic_paper_explorer.backend.generation.prompts import DEFAULT_SYSTEM_PROMPT
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


def test_generation_service_uses_detailed_default_system_prompt() -> None:
    service = GenerationService(provider=FakeProvider())

    assert "Answer using only the provided paper context" in service._system_prompt
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
    assert "Answer using only the context above" in prompt


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
