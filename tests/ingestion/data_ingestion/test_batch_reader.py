"""Tests for the paginated arXiv batch reader."""

import asyncio

from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import (
    ArxivPaperRecord,
    ArxivSearchResult,
)
from agentic_paper_explorer.ingestion.data_ingestion.batch_reader import iter_arxiv_papers


def _make_paper(paper_id: str) -> ArxivPaperRecord:
    return ArxivPaperRecord(
        paper_id=paper_id,
        title=paper_id,
        summary="summary",
        published="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        authors=[],
        categories=[],
        primary_category=None,
        comment=None,
        journal_reference=None,
        pdf_url=None,
        entry_url=None,
    )


class FakeArxivClient:
    def __init__(self, pages: list[ArxivSearchResult]) -> None:
        self._pages = pages
        self.calls: list[dict[str, object]] = []

    async def search_papers(
        self, *, search_query: str, start: int, max_results: int
    ) -> ArxivSearchResult:
        self.calls.append(
            {"search_query": search_query, "start": start, "max_results": max_results}
        )
        return self._pages[len(self.calls) - 1]


async def _collect_pages(client: FakeArxivClient, **kwargs: object) -> list[list[ArxivPaperRecord]]:
    return [page async for page in iter_arxiv_papers(client, **kwargs)]  # type: ignore[arg-type]


def test_iter_arxiv_papers_stops_when_start_reaches_total_results() -> None:
    pages = [
        ArxivSearchResult(
            total_results=3,
            start_index=0,
            items_per_page=2,
            papers=[_make_paper("p1"), _make_paper("p2")],
        ),
        ArxivSearchResult(
            total_results=3, start_index=2, items_per_page=2, papers=[_make_paper("p3")]
        ),
    ]
    client = FakeArxivClient(pages)

    result = asyncio.run(_collect_pages(client, search_query="all:graph", max_results_per_page=2))

    assert [paper.paper_id for page in result for paper in page] == ["p1", "p2", "p3"]
    assert client.calls == [
        {"search_query": "all:graph", "start": 0, "max_results": 2},
        {"search_query": "all:graph", "start": 2, "max_results": 2},
    ]


def test_iter_arxiv_papers_stops_when_page_is_empty() -> None:
    pages = [ArxivSearchResult(total_results=10, start_index=0, items_per_page=2, papers=[])]
    client = FakeArxivClient(pages)

    result = asyncio.run(_collect_pages(client, search_query="all:graph", max_results_per_page=2))

    assert result == []


def test_iter_arxiv_papers_stops_when_max_total_results_reached() -> None:
    pages = [
        ArxivSearchResult(
            total_results=100,
            start_index=0,
            items_per_page=2,
            papers=[_make_paper("p1"), _make_paper("p2")],
        ),
    ]
    client = FakeArxivClient(pages)

    result = asyncio.run(
        _collect_pages(
            client, search_query="all:graph", max_results_per_page=2, max_total_results=2
        )
    )

    assert len(result) == 1
    assert len(client.calls) == 1
