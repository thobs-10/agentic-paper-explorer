"""Tests for the generation API route and retrieval-to-generation wiring."""

import pytest
from fastapi.testclient import TestClient

from agentic_paper_explorer.backend.api import router as router_module
from agentic_paper_explorer.backend.api.router import app
from agentic_paper_explorer.backend.generation.service import (
    GenerationResult,
    GenerationStreamEvent,
)
from agentic_paper_explorer.backend.retrieval.service import RetrievalResult, RetrievedChunk


class StubRetrievalService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def search(self, query: str) -> RetrievalResult:
        self.calls.append(query)
        return RetrievalResult(
            query=query,
            chunks=[
                RetrievedChunk(
                    paper_id="paper-1",
                    title="Retrieval Overview",
                    text="This paper explains retrieval.",
                    score=0.92,
                    source_url="https://arxiv.org/abs/paper-1",
                )
            ],
            cached=False,
        )


class StubGenerationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[RetrievedChunk]]] = []

    async def answer_question(self, query: str, chunks: list[RetrievedChunk]) -> GenerationResult:
        self.calls.append((query, chunks))
        return GenerationResult(
            answer="This paper explains retrieval in a practical way.",
            sources=["https://arxiv.org/abs/paper-1"],
            model="stub-model",
        )

    async def stream_answer(self, query: str, chunks: list[RetrievedChunk]):
        yield GenerationStreamEvent(event="chunk", data={"text": "Partial answer [1]."})
        yield GenerationStreamEvent(
            event="complete",
            data={"sources": ["https://arxiv.org/abs/paper-1"], "model": "stub-model"},
        )


def test_generation_route_wires_retrieval_and_generation() -> None:
    retrieval_service = StubRetrievalService()
    generation_service = StubGenerationService()

    app.dependency_overrides.clear()

    from agentic_paper_explorer.backend.api.router import (
        get_generation_service,
        get_retrieval_service,
    )

    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_generation_service] = lambda: generation_service

    client = TestClient(app)
    response = client.post(
        "/api/v1/generation/answer",
        json={"query": "What is retrieval?"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "What is retrieval?"
    assert payload["answer"] == "This paper explains retrieval in a practical way."
    assert payload["sources"] == ["https://arxiv.org/abs/paper-1"]
    assert retrieval_service.calls == ["What is retrieval?"]
    assert generation_service.calls[0][0] == "What is retrieval?"


def test_generation_stream_route_returns_sse_events() -> None:
    retrieval_service = StubRetrievalService()
    generation_service = StubGenerationService()

    from agentic_paper_explorer.backend.api.router import (
        get_generation_service,
        get_retrieval_service,
    )

    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_generation_service] = lambda: generation_service

    client = TestClient(app)
    response = client.post(
        "/api/v1/generation/answer/stream",
        json={"query": "What is retrieval?"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: start" in response.text
    assert 'event: chunk\ndata: {"text": "Partial answer [1]."}' in response.text
    assert (
        'event: complete\ndata: {"sources": ["https://arxiv.org/abs/paper-1"], "model": "stub-model"}'
        in response.text
    )


def test_generation_route_returns_502_with_sources_when_generation_is_degraded() -> None:
    class DegradedGenerationService(StubGenerationService):
        async def answer_question(
            self, query: str, chunks: list[RetrievedChunk]
        ) -> GenerationResult:
            return GenerationResult(
                answer="I could not generate an answer right now.",
                sources=["https://arxiv.org/abs/paper-1"],
                model="stub-model",
                degraded=True,
                error_category="rate_limit",
            )

    from agentic_paper_explorer.backend.api.router import (
        get_generation_service,
        get_retrieval_service,
    )

    app.dependency_overrides.clear()
    app.dependency_overrides[get_retrieval_service] = lambda: StubRetrievalService()
    app.dependency_overrides[get_generation_service] = lambda: DegradedGenerationService()

    response = TestClient(app).post(
        "/api/v1/generation/answer",
        json={"query": "What is retrieval?"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 502
    payload = response.json()
    assert payload["degraded"] is True
    assert payload["error_category"] == "rate_limit"
    assert payload["sources"] == ["https://arxiv.org/abs/paper-1"]


def test_lifespan_wires_qdrant_and_redis_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, str] = {}
    closed_caches: list["FakeCache"] = []

    class FakeRepository:
        def __init__(self, *, url: str, collection_name: str) -> None:
            created["qdrant_url"] = url
            created["collection_name"] = collection_name
            self.closed = False

        async def search_points(self, **kwargs: object) -> list[dict[str, object]]:
            return []

        async def close(self) -> None:
            self.closed = True

    class FakeCache:
        def __init__(self) -> None:
            self.closed = False

        @classmethod
        def from_url(cls, url: str) -> "FakeCache":
            created["redis_url"] = url
            instance = cls()
            closed_caches.append(instance)
            return instance

        async def get(self, key: str) -> object | None:
            return None

        async def set(self, key: str, value: object, *, ttl: int | None = None) -> None:
            return None

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(router_module, "QdrantRepository", FakeRepository)
    monkeypatch.setattr(router_module, "RedisCache", FakeCache)

    app.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.app.state.retrieval_service is not None
        assert client.app.state.generation_service is not None

    assert created["qdrant_url"] == router_module.settings.qdrant_url
    assert created["redis_url"] == router_module.settings.redis_url
    assert closed_caches[0].closed is True


def test_health_endpoint_reports_backend_service() -> None:
    app.dependency_overrides.clear()
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend"}
