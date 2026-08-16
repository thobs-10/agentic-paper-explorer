"""Tests for the generation API route and retrieval-to-generation wiring."""

from fastapi.testclient import TestClient

from agentic_paper_explorer.backend.api.router import app
from agentic_paper_explorer.backend.generation.service import GenerationResult
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


def test_generation_route_wires_retrieval_and_generation() -> None:
    retrieval_service = StubRetrievalService()
    generation_service = StubGenerationService()

    app.dependency_overrides.clear()
    app.dependency_overrides[app.dependency_overrides.get] = lambda *args, **kwargs: None

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
