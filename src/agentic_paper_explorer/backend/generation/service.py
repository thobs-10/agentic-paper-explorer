"""LLM generation service that answers from retrieved paper context."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from agentic_paper_explorer.backend.generation.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    INSUFFICIENT_CONTEXT_MESSAGE,
)
from agentic_paper_explorer.backend.generation.provider import ProviderError
from agentic_paper_explorer.backend.retrieval.service import RetrievedChunk

logger = logging.getLogger(__name__)


class ProviderProtocol(Protocol):
    """Minimal model-provider contract used by the generation layer."""

    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str: ...

    def generate_stream(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]: ...


GENERATION_FAILURE_MESSAGE = (
    "I could not generate an answer right now. Please try again shortly. "
    "The retrieved paper sources are included below for reference."
)

STREAM_FAILURE_MESSAGE = "I could not complete the answer. Please try again shortly."


@dataclass(slots=True)
class GenerationResult:
    """Structured answer returned by the generation service."""

    answer: str
    sources: list[str] = field(default_factory=list)
    model: str | None = None
    degraded: bool = False
    error_category: str | None = None


@dataclass(slots=True, frozen=True)
class GenerationStreamEvent:
    """Client-facing event emitted while an answer is being generated."""

    event: str
    data: dict[str, object]


class GenerationService:
    """Build a prompt from retrieval context and call a provider."""

    def __init__(
        self,
        *,
        provider: ProviderProtocol,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> None:
        self._provider = provider
        self._system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self._temperature = temperature
        self._model = model

    def build_prompt(self, query: str, chunks: list[RetrievedChunk]) -> str:
        """Assemble a citation-aware prompt from the highest-scoring context chunks."""
        ordered_chunks = self._order_chunks(chunks)
        context_lines = [
            self._format_context_chunk(index, chunk)
            for index, chunk in enumerate(ordered_chunks, start=1)
        ]
        context_block = (
            "\n\n".join(context_lines) if context_lines else "No paper context was found."
        )
        return (
            "Answer the question using only the numbered paper excerpts below.\n\n"
            f"Question: {query}\n\n"
            "Context:\n"
            f"{context_block}\n\n"
            "Return a concise, direct answer. Cite each material claim with the relevant "
            "numbered marker, for example [1]. If the excerpts do not support an answer, "
            "say that the evidence is insufficient instead of guessing."
        )

    @staticmethod
    def _order_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Order chunks by relevance while preserving input order for ties."""
        return sorted(chunks, key=lambda chunk: chunk.score, reverse=True)

    @staticmethod
    def _format_context_chunk(index: int, chunk: RetrievedChunk) -> str:
        """Format one context chunk with a stable citation marker and source identity."""
        source = chunk.source_url or chunk.paper_id
        return f"[{index}] {chunk.title}\nSource: {source}\nExcerpt:\n{chunk.text}"

    @staticmethod
    def _source_urls(chunks: list[RetrievedChunk]) -> list[str]:
        """Return unique source URLs in ranked context order."""
        sources: list[str] = []
        for chunk in chunks:
            if chunk.source_url and chunk.source_url not in sources:
                sources.append(chunk.source_url)
        return sources

    async def answer_question(self, query: str, chunks: list[RetrievedChunk]) -> GenerationResult:
        """Generate an answer from the retrieved paper context."""
        ordered_chunks = self._order_chunks(chunks)
        if not any(chunk.text.strip() for chunk in ordered_chunks):
            return GenerationResult(
                answer=INSUFFICIENT_CONTEXT_MESSAGE,
                sources=self._source_urls(ordered_chunks),
                model=self._model,
            )

        prompt = self.build_prompt(query, chunks)
        error_category: str | None = None
        try:
            answer_text = await self._provider.generate(
                prompt=prompt,
                system_prompt=self._system_prompt,
                temperature=self._temperature,
            )
        except ProviderError as exc:
            logger.error("Generation failed category=%s retryable=%s", exc.category, exc.retryable)
            answer_text = GENERATION_FAILURE_MESSAGE
            error_category = exc.category
        except Exception:
            logger.exception("Generation failed with an unexpected provider error")
            answer_text = GENERATION_FAILURE_MESSAGE
            error_category = "internal"
        return GenerationResult(
            answer=answer_text,
            sources=self._source_urls(ordered_chunks),
            model=self._model,
            degraded=error_category is not None,
            error_category=error_category,
        )

    async def stream_answer(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> AsyncIterator[GenerationStreamEvent]:
        """Stream answer deltas followed by completion metadata."""
        ordered_chunks = self._order_chunks(chunks)
        sources = self._source_urls(ordered_chunks)
        if not any(chunk.text.strip() for chunk in ordered_chunks):
            yield GenerationStreamEvent(
                event="chunk",
                data={"text": INSUFFICIENT_CONTEXT_MESSAGE},
            )
            yield self._complete_event(sources)
            return

        prompt = self.build_prompt(query, chunks)
        error_category: str | None = None
        try:
            async for delta in self._provider.generate_stream(
                prompt=prompt,
                system_prompt=self._system_prompt,
                temperature=self._temperature,
            ):
                yield GenerationStreamEvent(event="chunk", data={"text": delta})
        except ProviderError as exc:
            logger.error(
                "Streaming generation failed category=%s retryable=%s", exc.category, exc.retryable
            )
            error_category = exc.category
        except Exception:
            logger.exception("Streaming generation failed with an unexpected provider error")
            error_category = "internal"

        if error_category is not None:
            yield GenerationStreamEvent(
                event="error",
                data={"message": STREAM_FAILURE_MESSAGE, "category": error_category},
            )
        yield self._complete_event(sources, error_category)

    def _complete_event(
        self, sources: list[str], error_category: str | None = None
    ) -> GenerationStreamEvent:
        return GenerationStreamEvent(
            event="complete",
            data={
                "sources": sources,
                "model": self._model,
                "degraded": error_category is not None,
                "error_category": error_category,
            },
        )

    async def generate(self, query: str, chunks: list[RetrievedChunk]) -> GenerationResult:
        """Backward-compatible alias for the generation flow."""
        return await self.answer_question(query, chunks)
