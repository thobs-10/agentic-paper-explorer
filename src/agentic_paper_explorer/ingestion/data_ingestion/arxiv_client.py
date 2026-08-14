"""Client utilities for fetching papers from the arXiv API."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlencode

import httpx
from defusedxml import ElementTree as DefusedElementTree

ATOM_NAMESPACE: Final[dict[str, str]] = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
ARXIV_API_URL: Final[str] = "https://export.arxiv.org/api/query"
ARXIV_USER_AGENT: Final[str] = "agentic-paper-explorer/0.1.0"
# arXiv responds with these on transient upstream issues; anything else fails fast.
RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({500, 502, 503, 504})


@dataclass(slots=True, frozen=True)
class ArxivPaperRecord:
    """Normalized paper data returned from the arXiv API."""

    paper_id: str
    title: str
    summary: str
    published: str
    updated: str
    authors: list[str]
    categories: list[str]
    primary_category: str | None
    comment: str | None
    journal_reference: str | None
    pdf_url: str | None
    entry_url: str | None


@dataclass(slots=True, frozen=True)
class ArxivSearchResult:
    """Container for an arXiv search response."""

    total_results: int
    start_index: int
    items_per_page: int
    papers: list[ArxivPaperRecord]


class ArxivClient:
    """Minimal arXiv REST client backed by the public Atom feed."""

    def __init__(
        self,
        base_url: str = ARXIV_API_URL,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        min_request_interval_seconds: float = 3.0,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._min_request_interval_seconds = min_request_interval_seconds
        # A single pooled client is reused across calls instead of one per request.
        self._client = httpx.Client(
            timeout=timeout_seconds, headers={"User-Agent": ARXIV_USER_AGENT}
        )
        self._last_request_at: float | None = None

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> ArxivClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    async def search_papers(
        self,
        *,
        search_query: str,
        start: int = 0,
        max_results: int = 10,
    ) -> ArxivSearchResult:
        """Fetch papers from arXiv for a query window.
        Args:
            search_query: The arXiv search query string, e.g. "all:transformer".
            start: Zero-based index for the first result to fetch.
            max_results: Number of results to fetch (max 100).
        Returns:
            An `ArxivSearchResult` containing the normalized paper records.
        """
        # using asyncio.to_thread to run the synchronous code in a separate thread to avoid blocking the event loop
        return await asyncio.to_thread(
            self._search_papers_sync,
            search_query=search_query,
            start=start,
            max_results=max_results,
        )

    def _search_papers_sync(
        self,
        *,
        search_query: str,
        start: int,
        max_results: int,
    ) -> ArxivSearchResult:
        """Fetch papers from arXiv for a query window (synchronous).

        Args:
            search_query (str): The arXiv search query string, e.g. "all:transformer".
            start (int): Zero-based index for the first result to fetch.
            max_results (int): Number of results to fetch (max 100).

        Returns:
            ArxivSearchResult: The normalized paper records.
        """
        # Build the query string and request URL
        query_string = urlencode(
            {
                "search_query": search_query,
                "start": start,
                "max_results": max_results,
            }
        )
        request_url = f"{self._base_url}?{query_string}"
        payload = self._get_with_retry(request_url)
        return self.parse_search_response(payload)

    def _get_with_retry(self, request_url: str) -> str:
        """Fetch a URL, rate-limited and with bounded retries on transient failures."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            # custom rate limiting to avoid hitting arXiv's request limits
            self._wait_for_rate_limit()
            try:
                response = self._client.get(request_url)
                response.raise_for_status()
                return response.text
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in RETRYABLE_STATUS_CODES:
                    raise
                last_error = exc
            if attempt < self._max_retries:
                time.sleep(self._retry_backoff_seconds * (2**attempt))
        raise last_error  # type: ignore[misc]

    def _wait_for_rate_limit(self) -> None:
        """Enforce a minimum spacing between outgoing arXiv requests."""
        if self._last_request_at is not None:
            remaining = self._min_request_interval_seconds - (
                time.monotonic() - self._last_request_at
            )
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    @staticmethod
    def parse_search_response(payload: str) -> ArxivSearchResult:
        """Parse an arXiv Atom feed payload into normalized records."""

        root = DefusedElementTree.fromstring(payload)
        papers = [
            ArxivClient._parse_entry(entry) for entry in root.findall("atom:entry", ATOM_NAMESPACE)
        ]
        return ArxivSearchResult(
            total_results=ArxivClient._parse_int(root, "opensearch:totalResults"),
            start_index=ArxivClient._parse_int(root, "opensearch:startIndex"),
            items_per_page=ArxivClient._parse_int(root, "opensearch:itemsPerPage"),
            papers=papers,
        )

    @staticmethod
    def _parse_entry(entry: Any) -> ArxivPaperRecord:
        """Parse a single Atom entry into a normalized paper record."""
        return ArxivPaperRecord(
            paper_id=ArxivClient._read_text(entry, "atom:id") or "",
            title=ArxivClient._normalize_text(ArxivClient._read_text(entry, "atom:title") or ""),
            summary=ArxivClient._normalize_text(
                ArxivClient._read_text(entry, "atom:summary") or ""
            ),
            published=ArxivClient._read_text(entry, "atom:published") or "",
            updated=ArxivClient._read_text(entry, "atom:updated") or "",
            authors=[
                ArxivClient._normalize_text(author.text or "")
                for author in entry.findall("atom:author/atom:name", ATOM_NAMESPACE)
                if (author.text or "").strip()
            ],
            categories=[
                category.attrib["term"]
                for category in entry.findall("atom:category", ATOM_NAMESPACE)
                if category.attrib.get("term")
            ],
            primary_category=ArxivClient._read_attribute(entry, "arxiv:primary_category", "term"),
            comment=ArxivClient._normalize_optional_text(
                ArxivClient._read_text(entry, "arxiv:comment")
            ),
            journal_reference=ArxivClient._normalize_optional_text(
                ArxivClient._read_text(entry, "arxiv:journal_ref")
            ),
            pdf_url=ArxivClient._find_link(entry, title="pdf"),
            entry_url=ArxivClient._find_link(entry, rel="alternate"),
        )

    # static methods to extract and normalize data from the Atom feed.

    @staticmethod
    def _parse_int(root: Any, path: str) -> int:
        """Parse an integer value from the Atom feed, defaulting to 0 if missing."""
        return int(ArxivClient._read_text(root, path) or 0)

    @staticmethod
    def _read_text(node: Any, path: str) -> str | None:
        """Read the text content of a child element, returning None if not found."""
        child = node.find(path, ATOM_NAMESPACE)
        return child.text if child is not None else None

    @staticmethod
    def _read_attribute(node: Any, path: str, attribute_name: str) -> str | None:
        """Read the value of an attribute from a child element, returning None if not found."""
        child = node.find(path, ATOM_NAMESPACE)
        if child is None:
            return None
        return child.attrib.get(attribute_name)

    @staticmethod
    def _find_link(
        node: Any,
        *,
        rel: str | None = None,
        title: str | None = None,
    ) -> str | None:
        """Find a link element with the specified rel and/or title attributes, returning its href if found."""
        for link in node.findall("atom:link", ATOM_NAMESPACE):
            if rel is not None and link.attrib.get("rel") != rel:
                continue
            if title is not None and link.attrib.get("title") != title:
                continue
            href = link.attrib.get("href")
            if href:
                return href
        return None

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Normalize whitespace in a string by collapsing multiple spaces and trimming."""
        return " ".join(value.split())

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        """Normalize whitespace in a string, returning None if the result is empty or the input is None."""
        if value is None:
            return None
        normalized = ArxivClient._normalize_text(value)
        return normalized or None
