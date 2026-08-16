"""LLM generation service that answers from retrieved paper context."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from agentic_paper_explorer.backend.generation.prompts import DEFAULT_SYSTEM_PROMPT
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


@dataclass(slots=True)
class GenerationResult:
    """Structured answer returned by the generation service."""

    answer: str
    sources: list[str] = field(default_factory=list)
    model: str | None = None


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
        """Assemble a generation prompt from a conceptual question and ranked chunks."""
        context_lines = [
            f"[Source: {chunk.source_url or chunk.paper_id}] {chunk.title}\n{chunk.text}"
            for chunk in chunks
        ]
        context_block = (
            "\n\n".join(context_lines) if context_lines else "No paper context was found."
        )
        return (
            "You are answering from the paper context below.\n\n"
            f"Question: {query}\n\n"
            "Context:\n"
            f"{context_block}\n\n"
            "Answer using only the context above. Be concise, evidence-based, and include"
            " source references when they are relevant."
        )

    async def answer_question(self, query: str, chunks: list[RetrievedChunk]) -> GenerationResult:
        """Generate an answer from the retrieved paper context."""
        prompt = self.build_prompt(query, chunks)
        try:
            answer_text = await self._provider.generate(
                prompt=prompt,
                system_prompt=self._system_prompt,
                temperature=self._temperature,
            )
        except ProviderError as exc:
            logger.error("Generation fallback used category=%s", exc.category)
            answer_text = (
                "I could not generate an answer right now. Please try again shortly. "
                "The retrieved paper sources are included below for reference."
            )
        except Exception:
            logger.exception("Generation fallback used for unexpected provider failure")
            answer_text = (
                "I could not generate an answer right now. Please try again shortly. "
                "The retrieved paper sources are included below for reference."
            )
        sources = [chunk.source_url for chunk in chunks if chunk.source_url]
        return GenerationResult(answer=answer_text, sources=sources, model=self._model)

    async def generate(self, query: str, chunks: list[RetrievedChunk]) -> GenerationResult:
        """Backward-compatible alias for the generation flow."""
        return await self.answer_question(query, chunks)
