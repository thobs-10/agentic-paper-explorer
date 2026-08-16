"""FastAPI routes for backend generation and retrieval orchestration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentic_paper_explorer.backend.api.models import GenerationRequest, GenerationResponse
from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider
from agentic_paper_explorer.backend.generation.service import GenerationResult, GenerationService
from agentic_paper_explorer.backend.retrieval.service import RetrievalResult, RetrievalService
from agentic_paper_explorer.configs.settings import get_settings

settings = get_settings()


class _MemoryCache:
    """Simple in-memory cache used as a default retrieval backend."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str) -> Any | None:
        return self._store.get(key)

    async def set(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        self._store[key] = value


class _EmptyVectorRepository:
    """Fallback repository returning no matches until a real backend is wired in."""

    async def search_points(
        self,
        *,
        query_vector: list[float],
        limit: int,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        return []


app = FastAPI(
    title="Agentic Paper Explorer Backend",
    description="Retrieval and generation API for grounded paper answers.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api/v1", tags=["backend"])


async def get_retrieval_service() -> RetrievalService:
    """Return a retrieval service instance for backend handlers."""
    return RetrievalService(
        cache=_MemoryCache(),
        repository=_EmptyVectorRepository(),
        embedder=lambda text: [0.1, 0.2, 0.3],
    )


async def get_generation_service() -> GenerationService:
    """Create a generation service backed by LiteLLM from settings."""
    provider = LiteLLMProvider(
        model=settings.llm_model_name,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        retry_backoff_seconds=settings.llm_retry_backoff_seconds,
    )
    return GenerationService(provider=provider, model=settings.llm_model_name)


@api_router.post("/generation/answer", response_model=GenerationResponse)
async def answer_question(
    request: GenerationRequest,
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    generation_service: GenerationService = Depends(get_generation_service),
) -> GenerationResponse:
    """Retrieve relevant paper context and answer the user's question grounded in it."""
    retrieval_result: RetrievalResult = await retrieval_service.search(request.query)
    generation_result: GenerationResult = await generation_service.answer_question(
        request.query,
        retrieval_result.chunks,
    )
    return GenerationResponse(
        query=request.query,
        answer=generation_result.answer,
        sources=generation_result.sources,
        model=generation_result.model,
    )


app.include_router(api_router)
