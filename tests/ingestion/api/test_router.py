"""Tests for the ingestion API router."""

from fastapi.testclient import TestClient

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


def test_get_arxiv_client_returns_arxiv_client_instance() -> None:
    client = get_arxiv_client()

    assert isinstance(client, ArxivClient)


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
