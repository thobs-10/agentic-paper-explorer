"""Retrieval orchestration for cached and vector-backed paper lookup."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


class CacheProtocol(Protocol):
    """Minimal Redis-like cache contract used by the retrieval layer."""

    async def get(self, key: str) -> object | None: ...

    async def set(
        self,
        key: str,
        value: object,
        *,
        ttl: int | None = None,
    ) -> None: ...


class RepositoryProtocol(Protocol):
    """Minimal vector repository contract used by the retrieval layer."""

    async def search_points(
        self,
        *,
        query_vector: list[float],
        limit: int,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(slots=True, frozen=True)
class RetrievedChunk:
    """A ranked chunk ready to be passed to the generation stage."""

    paper_id: str
    title: str
    text: str
    score: float
    source_url: str | None = None


@dataclass(slots=True)
class RetrievalResult:
    """Result bundle produced by the retrieval service."""

    query: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    cached: bool = False


class RetrievalService:
    """Fetch cached or vector-based context for a user query."""

    def __init__(
        self,
        *,
        cache: CacheProtocol,
        repository: RepositoryProtocol,
        embedder: Any,
        score_threshold: float = 0.2,
        top_k: int = 5,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._cache = cache
        self._repository = repository
        self._embedder = embedder
        self._score_threshold = score_threshold
        self._top_k = top_k
        self._cache_ttl_seconds = cache_ttl_seconds

    def _cache_key(self, query: str) -> str:
        normalized = " ".join(query.lower().split())
        tokens = re.findall(r"[a-z0-9]+", normalized)
        slug = "-".join(tokens)
        return f"prompt:{slug or 'empty-query'}"

    @staticmethod
    def _normalize_chunk(payload: dict[str, Any], score: float) -> RetrievedChunk:
        return RetrievedChunk(
            paper_id=str(payload.get("paper_id", "unknown")),
            title=str(payload.get("title") or "Untitled"),
            text=str(payload.get("text") or ""),
            score=float(score),
            source_url=str(payload.get("entry_url") or payload.get("pdf_url") or None),
        )

    async def search(self, query: str) -> RetrievalResult:
        """Check Redis, then fall back to vector search, then rerank and package context."""
        cache_key = self._cache_key(query)
        cached_hit = await self._cache.get(cache_key)
        if isinstance(cached_hit, dict):
            chunks = [
                RetrievedChunk(
                    paper_id=str(item["paper_id"]),
                    title=str(item["title"]),
                    text=str(item["text"]),
                    score=float(item.get("score", 0.0)),
                    source_url=item.get("source_url"),
                )
                for item in cached_hit.get("chunks", [])
            ]
            return RetrievalResult(query=query, chunks=chunks, cached=True)

        query_vector = self._embedder(query)
        matches = await self._repository.search_points(
            query_vector=query_vector,
            limit=self._top_k,
            score_threshold=self._score_threshold,
        )
        ranked_chunks: list[RetrievedChunk] = []
        for match in matches:
            score = float(match.get("score", 0.0))
            if score < self._score_threshold:
                continue
            payload = match.get("payload") or {}
            ranked_chunks.append(self._normalize_chunk(payload, score))

        result = RetrievalResult(query=query, chunks=ranked_chunks)
        await self._cache.set(
            cache_key,
            {
                "query": query,
                "chunks": [
                    {
                        "paper_id": chunk.paper_id,
                        "title": chunk.title,
                        "text": chunk.text,
                        "score": chunk.score,
                        "source_url": chunk.source_url,
                    }
                    for chunk in ranked_chunks
                ],
            },
            ttl=self._cache_ttl_seconds,
        )
        return result
