"""Paginated batch reading over the arXiv search API."""

from __future__ import annotations

from collections.abc import AsyncIterator

from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import (
    ArxivClient,
    ArxivPaperRecord,
)


async def iter_arxiv_papers(
    client: ArxivClient,
    *,
    search_query: str,
    max_results_per_page: int,
    max_total_results: int | None = None,
) -> AsyncIterator[list[ArxivPaperRecord]]:
    """Yield successive pages of papers for a search query.

    Pages until arXiv reports no more results, or until `max_total_results`
    papers have been yielded (useful for bounding ad-hoc/manual runs).

    Args:
        client: An `ArxivClient` instance to use for API calls.
        search_query: The search query to use for the arXiv API.
        max_results_per_page: The maximum number of results to fetch per page.
        max_total_results: Optional maximum number of total results to fetch.
    Yields:
        Lists of `ArxivPaperRecord` objects, one list per page of results.
    """
    start = 0
    fetched = 0
    while True:
        result = await client.search_papers(
            search_query=search_query,
            start=start,
            max_results=max_results_per_page,
        )
        if not result.papers:
            return

        yield result.papers

        fetched += len(result.papers)
        start += max_results_per_page
        if start >= result.total_results:
            return
        if max_total_results is not None and fetched >= max_total_results:
            return
