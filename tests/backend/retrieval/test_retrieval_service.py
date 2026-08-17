"""Tests for retrieval orchestration and Qdrant-backed lookups."""

import asyncio
from uuid import uuid4

import pytest

from agentic_paper_explorer.backend.database.qdrant_client import QdrantRepository
from agentic_paper_explorer.backend.retrieval.service import (
    RetrievalService,
)


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.set_calls: list[tuple[str, object, int | None]] = []

    async def get(self, key: str) -> object | None:
        return self.store.get(key)

    async def set(self, key: str, value: object, *, ttl: int | None = None) -> None:
        self.store[key] = value
        self.set_calls.append((key, value, ttl))


class FakeRepo:
    def __init__(self, hits: list[dict[str, object]]) -> None:
        self.hits = hits
        self.search_calls: list[dict[str, object]] = []

    async def search_points(
        self,
        *,
        query_vector: list[float],
        limit: int,
        score_threshold: float | None = None,
    ) -> list[dict[str, object]]:
        self.search_calls.append(
            {
                "query_vector": query_vector,
                "limit": limit,
                "score_threshold": score_threshold,
            }
        )
        return self.hits


@pytest.fixture()
def fake_cache() -> FakeCache:
    return FakeCache()


def test_qdrant_repository_search_points_returns_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeScoredPoint:
        def __init__(self, point_id: str, score: float, payload: dict[str, object]) -> None:
            self.id = point_id
            self.score = score
            self.payload = payload

    class FakeQueryResponse:
        def __init__(self, points: list[FakeScoredPoint]) -> None:
            self.points = points

    class FakeAsyncQdrantClient:
        def __init__(self, *, url: str) -> None:
            self.url = url
            self.search_calls: list[dict[str, object]] = []

        async def query_points(
            self,
            *,
            collection_name: str,
            query: list[float],
            limit: int,
            score_threshold: float | None = None,
            with_payload: bool = True,
        ) -> FakeQueryResponse:
            self.search_calls.append(
                {
                    "collection_name": collection_name,
                    "query": query,
                    "limit": limit,
                    "score_threshold": score_threshold,
                }
            )
            return FakeQueryResponse(
                [
                    FakeScoredPoint(
                        "12345678-1234-4234-8234-123456789abc",
                        0.95,
                        {"text": "retrieved chunk", "paper_id": "paper-1"},
                    )
                ]
            )

    monkeypatch.setattr(QdrantRepository, "_client", None, raising=False)
    monkeypatch.setattr(QdrantRepository, "_collection_name", "arxiv_papers", raising=False)

    repository = QdrantRepository(url="http://localhost:6333", collection_name="arxiv_papers")
    client = FakeAsyncQdrantClient(url="http://localhost:6333")
    repository._client = client

    hits = asyncio.run(
        repository.search_points(query_vector=[0.1, 0.2, 0.3], limit=5, score_threshold=0.1)
    )

    assert client.search_calls[0]["query"] == [0.1, 0.2, 0.3]
    assert hits[0]["score"] == 0.95
    assert hits[0]["payload"] == {"text": "retrieved chunk", "paper_id": "paper-1"}


def test_retrieval_service_uses_cache_when_prompt_is_cached(fake_cache: FakeCache) -> None:
    cached_payload = {
        "query": "What is retrieval?",
        "chunks": [
            {
                "paper_id": "paper-1",
                "title": "Retrieval Overview",
                "text": "This paper explains retrieval.",
                "score": 0.88,
                "source_url": "https://arxiv.org/abs/paper-1",
            }
        ],
    }
    fake_cache.store["prompt:what-is-retrieval"] = cached_payload

    repo = FakeRepo([])
    service = RetrievalService(
        cache=fake_cache,
        repository=repo,
        embedder=lambda text: [0.1, 0.2, 0.3],
    )

    result = asyncio.run(service.search("What is retrieval?"))

    assert result.cached is True
    assert result.chunks[0].paper_id == "paper-1"
    assert repo.search_calls == []


def test_retrieval_service_falls_back_to_vector_search_and_caches_result(
    fake_cache: FakeCache,
) -> None:
    repo = FakeRepo(
        [
            {
                "id": str(uuid4()),
                "score": 0.87,
                "payload": {
                    "paper_id": "paper-2",
                    "title": "Ranking in RAG",
                    "text": "Ranked retrieval improves answer accuracy.",
                    "entry_url": "https://arxiv.org/abs/paper-2",
                },
            }
        ]
    )
    service = RetrievalService(
        cache=fake_cache,
        repository=repo,
        embedder=lambda text: [0.1, 0.2, 0.3],
    )

    result = asyncio.run(service.search("rank retrieval pipelines"))

    assert result.cached is False
    assert repo.search_calls
    assert result.chunks[0].paper_id == "paper-2"
    assert fake_cache.set_calls


def test_search_awaits_async_embedder(fake_cache: FakeCache) -> None:
    repo = FakeRepo(
        [
            {
                "id": "point-3",
                "score": 0.81,
                "payload": {
                    "paper_id": "paper-3",
                    "title": "Async Embedding",
                    "text": "Embedding runs off the event loop.",
                    "entry_url": "https://arxiv.org/abs/paper-3",
                },
            }
        ]
    )

    async def async_embedder(text: str) -> list[float]:
        return [0.4, 0.5, 0.6]

    service = RetrievalService(cache=fake_cache, repository=repo, embedder=async_embedder)

    result = asyncio.run(service.search("async embedding"))

    assert repo.search_calls[0]["query_vector"] == [0.4, 0.5, 0.6]
    assert result.chunks[0].paper_id == "paper-3"
