"""Tests for the ingestion API router."""

import pytest
from fastapi.testclient import TestClient

from agentic_paper_explorer.ingestion import pipeline as pipeline_module
from agentic_paper_explorer.ingestion.api.router import app, get_arxiv_client
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import (
    ArxivClient,
    ArxivPaperRecord,
    ArxivSearchResult,
)


class StubArxivClient:
    async def search_papers(
        self,
        *,
        search_query: str,
        start: int = 0,
        max_results: int = 10,
    ) -> ArxivSearchResult:
        return ArxivSearchResult(
            total_results=1,
            start_index=start,
            items_per_page=max_results,
            papers=[
                ArxivPaperRecord(
                    paper_id="paper-1",
                    title=f"Result for {search_query}",
                    summary="summary",
                    published="2026-01-01T00:00:00Z",
                    updated="2026-01-01T00:00:00Z",
                    authors=["Author One"],
                    categories=["cs.AI"],
                    primary_category="cs.AI",
                    comment=None,
                    journal_reference=None,
                    pdf_url="https://arxiv.org/pdf/paper-1",
                    entry_url="https://arxiv.org/abs/paper-1",
                )
            ],
        )


class FailingArxivClient:
    async def search_papers(
        self,
        *,
        search_query: str,
        start: int = 0,
        max_results: int = 10,
    ) -> ArxivSearchResult:
        raise RuntimeError("upstream arxiv failed")


def test_get_arxiv_client_returns_client_from_app_state() -> None:
    class FakeState:
        arxiv_client = ArxivClient()

    class FakeApp:
        state = FakeState()

    class FakeRequest:
        app = FakeApp()

    try:
        assert get_arxiv_client(FakeRequest()) is FakeApp.state.arxiv_client  # type: ignore[arg-type]
    finally:
        FakeState.arxiv_client.close()


def test_lifespan_creates_and_closes_shared_arxiv_client() -> None:
    with TestClient(app):
        assert isinstance(app.state.arxiv_client, ArxivClient)


def test_search_arxiv_papers_returns_bounded_response() -> None:
    app.dependency_overrides[get_arxiv_client] = StubArxivClient
    client = TestClient(app)

    response = client.get(
        "/api/v1/ingestion/papers/search",
        params={"search_query": "all:graph", "start": 5, "max_results": 2},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_results"] == 1
    assert payload["start_index"] == 5
    assert payload["items_per_page"] == 2
    assert payload["papers"][0]["title"] == "Result for all:graph"


def test_search_arxiv_papers_returns_502_on_upstream_failure() -> None:
    app.dependency_overrides[get_arxiv_client] = FailingArxivClient
    client = TestClient(app)

    response = client.get(
        "/api/v1/ingestion/papers/search",
        params={"search_query": "all:graph", "start": 0, "max_results": 1},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json() == {"detail": "Failed to fetch data from arXiv"}


def test_process_papers_runs_pipeline_from_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_ingestion_pipeline(
        search_query: str, *, max_total_results: int | None = None
    ) -> pipeline_module.IngestionSummary:
        assert search_query == "all:transformer"
        assert max_total_results == 5
        return pipeline_module.IngestionSummary(papers_processed=7, chunks_upserted=21)

    monkeypatch.setattr(
        "agentic_paper_explorer.ingestion.api.router.run_ingestion_pipeline",
        fake_run_ingestion_pipeline,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/ingestion/papers/process",
        json={"search_query": "all:transformer", "max_results": 5},
    )

    assert response.status_code == 200
    assert response.json() == {
        "search_query": "all:transformer",
        "papers_processed": 7,
        "chunks_upserted": 21,
    }
