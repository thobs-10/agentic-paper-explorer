"""FastAPI routes for backend generation and retrieval orchestration."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agentic_paper_explorer.backend.api.models import GenerationRequest, GenerationResponse
from agentic_paper_explorer.backend.database.qdrant_client import QdrantRepository
from agentic_paper_explorer.backend.database.redis_cache import RedisCache
from agentic_paper_explorer.backend.generation.provider import LiteLLMProvider
from agentic_paper_explorer.backend.generation.service import (
    GenerationResult,
    GenerationService,
    GenerationStreamEvent,
)
from agentic_paper_explorer.backend.retrieval.service import RetrievalResult, RetrievalService
from agentic_paper_explorer.configs.settings import get_settings
from agentic_paper_explorer.ingestion.processing.embeddings import embed_query

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build shared retrieval and generation collaborators once per process."""
    repository = QdrantRepository(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection_name,
    )
    cache = RedisCache.from_url(settings.redis_url)
    app.state.retrieval_service = RetrievalService(
        cache=cache,
        repository=repository,
        embedder=lambda text: embed_query(text, model_name=settings.embedding_model_name),
        score_threshold=settings.retrieval_score_threshold,
        top_k=settings.retrieval_top_k,
        cache_ttl_seconds=settings.retrieval_cache_ttl_seconds,
    )
    app.state.generation_service = GenerationService(
        provider=LiteLLMProvider(
            model=settings.llm_model_name,
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            retry_backoff_seconds=settings.llm_retry_backoff_seconds,
        ),
        temperature=settings.llm_temperature,
        model=settings.llm_model_name,
    )
    try:
        yield
    finally:
        await cache.close()
        await repository.close()


app = FastAPI(
    title="Agentic Paper Explorer Backend",
    description="Retrieval and generation API for grounded paper answers.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api/v1", tags=["backend"])


def get_retrieval_service(request: Request) -> RetrievalService:
    """Return the shared retrieval service created at app startup."""
    return request.app.state.retrieval_service


def get_generation_service(request: Request) -> GenerationService:
    """Return the shared generation service created at app startup."""
    return request.app.state.generation_service


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


@api_router.post("/generation/answer/stream")
async def stream_answer_question(
    request: GenerationRequest,
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    generation_service: GenerationService = Depends(get_generation_service),
) -> StreamingResponse:
    """Stream grounded answer text as Server-Sent Events."""
    retrieval_result: RetrievalResult = await retrieval_service.search(request.query)

    async def events():
        yield _format_sse_event(GenerationStreamEvent(event="start", data={"query": request.query}))
        async for event in generation_service.stream_answer(
            request.query,
            retrieval_result.chunks,
        ):
            yield _format_sse_event(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _format_sse_event(event: GenerationStreamEvent) -> str:
    """Serialize a generation event using the SSE wire format."""
    return f"event: {event.event}\ndata: {json.dumps(event.data)}\n\n"


app.include_router(api_router)
