"""Tests for the arXiv ingestion client."""

import asyncio

import httpx
import pytest
from defusedxml import ElementTree as DefusedElementTree

from agentic_paper_explorer.ingestion.data_ingestion import arxiv_client as arxiv_module
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import (
    ATOM_NAMESPACE,
    ArxivClient,
    ArxivPaperRecord,
    ArxivSearchResult,
)

SAMPLE_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <opensearch:itemsPerPage>1</opensearch:itemsPerPage>
  <opensearch:totalResults>184681</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <entry>
    <id>http://arxiv.org/abs/cond-mat/0011267v1</id>
    <title>The electronic structure of cuprates from high energy spectroscopy</title>
    <updated>2000-11-15T16:19:15Z</updated>
    <published>2000-11-15T16:19:15Z</published>
    <link href="https://arxiv.org/abs/cond-mat/0011267v1" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/cond-mat/0011267v1" rel="related" type="application/pdf" title="pdf"/>
    <summary>  We report studies of the electronic structure. </summary>
    <category term="cond-mat.supr-con" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cond-mat.str-el" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:comment>In press</arxiv:comment>
    <arxiv:primary_category term="cond-mat.supr-con"/>
    <arxiv:journal_ref>J. Electron Spectr. Relat. Phenom. 117-118, 203 (2001)</arxiv:journal_ref>
    <author>
      <name>Mark S. Golden</name>
    </author>
    <author>
      <name>Christian Duerr</name>
    </author>
  </entry>
</feed>
"""


def test_parse_search_response_returns_normalized_records() -> None:
    result = ArxivClient.parse_search_response(SAMPLE_FEED)

    assert result.total_results == 184681
    assert result.start_index == 0
    assert result.items_per_page == 1
    assert len(result.papers) == 1
    assert result.papers[0].paper_id == "http://arxiv.org/abs/cond-mat/0011267v1"
    assert result.papers[0].authors == ["Mark S. Golden", "Christian Duerr"]
    assert result.papers[0].categories == ["cond-mat.supr-con", "cond-mat.str-el"]
    assert result.papers[0].primary_category == "cond-mat.supr-con"
    assert result.papers[0].pdf_url == "https://arxiv.org/pdf/cond-mat/0011267v1"
    assert result.papers[0].entry_url == "https://arxiv.org/abs/cond-mat/0011267v1"
    assert result.papers[0].summary == "We report studies of the electronic structure."


def test_search_papers_uses_asyncio_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ArxivClient()
    expected = ArxivSearchResult(total_results=0, start_index=0, items_per_page=0, papers=[])
    captured: dict[str, object] = {}

    async def fake_to_thread(func: object, /, **kwargs: object) -> ArxivSearchResult:
        captured["func"] = func
        captured["kwargs"] = kwargs
        return expected

    monkeypatch.setattr(arxiv_module.asyncio, "to_thread", fake_to_thread)

    result = asyncio.run(client.search_papers(search_query="all:graph", start=3, max_results=7))

    assert result is expected
    assert captured["func"] == client._search_papers_sync
    assert captured["kwargs"] == {
        "search_query": "all:graph",
        "start": 3,
        "max_results": 7,
    }


def test_search_papers_sync_builds_request_and_reads_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ArxivSearchResult(total_results=1, start_index=1, items_per_page=2, papers=[])
    captured_payload: dict[str, str] = {}
    captured_request: dict[str, object] = {}

    class FakeResponse:
        text = "<feed></feed>"

        def raise_for_status(self) -> None:
            return None

    class FakeHttpxClient:
        def __init__(self, *, timeout: float, headers: dict[str, str]) -> None:
            captured_request["timeout"] = timeout
            captured_request["headers"] = headers

        def get(self, request_url: str) -> FakeResponse:
            captured_request["request_url"] = request_url
            return FakeResponse()

        def close(self) -> None:
            captured_request["closed"] = True

    def fake_parse(payload: str) -> ArxivSearchResult:
        captured_payload["value"] = payload
        return expected

    monkeypatch.setattr(arxiv_module.httpx, "Client", FakeHttpxClient)
    monkeypatch.setattr(ArxivClient, "parse_search_response", staticmethod(fake_parse))

    client = ArxivClient(timeout_seconds=12.5, min_request_interval_seconds=0)
    result = client._search_papers_sync(search_query="all:graph neural", start=2, max_results=5)

    assert captured_request["request_url"] == (
        "https://export.arxiv.org/api/query?search_query=all%3Agraph+neural&start=2&max_results=5"
    )
    assert captured_request["headers"] == {"User-Agent": "agentic-paper-explorer/0.1.0"}
    assert captured_request["timeout"] == 12.5
    assert captured_payload["value"] == "<feed></feed>"
    assert result is expected

    client.close()
    assert captured_request["closed"] is True


def test_get_with_retry_retries_on_retryable_status_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ArxivClient(max_retries=2, retry_backoff_seconds=0, min_request_interval_seconds=0)
    sleep_calls: list[float] = []
    monkeypatch.setattr(arxiv_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    class FailingThenOkResponse:
        def __init__(self, status_code: int | None) -> None:
            self._status_code = status_code
            self.text = "<feed></feed>"

        def raise_for_status(self) -> None:
            if self._status_code is not None:
                request = httpx.Request("GET", "https://example.test")
                raise httpx.HTTPStatusError(
                    "server error",
                    request=request,
                    response=httpx.Response(self._status_code, request=request),
                )

    responses = iter([FailingThenOkResponse(503), FailingThenOkResponse(None)])
    monkeypatch.setattr(client._client, "get", lambda _url: next(responses))

    payload = client._get_with_retry("https://example.test")

    assert payload == "<feed></feed>"
    assert len(sleep_calls) == 1


def test_get_with_retry_raises_immediately_on_non_retryable_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ArxivClient(max_retries=3, retry_backoff_seconds=0, min_request_interval_seconds=0)

    class BadRequestResponse:
        def raise_for_status(self) -> None:
            request = httpx.Request("GET", "https://example.test")
            raise httpx.HTTPStatusError(
                "bad request",
                request=request,
                response=httpx.Response(400, request=request),
            )

    monkeypatch.setattr(client._client, "get", lambda _url: BadRequestResponse())

    with pytest.raises(httpx.HTTPStatusError):
        client._get_with_retry("https://example.test")


def test_get_with_retry_raises_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ArxivClient(max_retries=2, retry_backoff_seconds=0, min_request_interval_seconds=0)
    monkeypatch.setattr(arxiv_module.time, "sleep", lambda _seconds: None)

    class AlwaysTimesOut:
        def raise_for_status(self) -> None:
            return None

    def fake_get(_url: str) -> AlwaysTimesOut:
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(client._client, "get", fake_get)

    with pytest.raises(httpx.TimeoutException):
        client._get_with_retry("https://example.test")


def test_wait_for_rate_limit_sleeps_for_remaining_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ArxivClient(min_request_interval_seconds=3.0)
    monotonic_values = iter([101.0, 101.0])
    monkeypatch.setattr(arxiv_module.time, "monotonic", lambda: next(monotonic_values))
    sleep_calls: list[float] = []
    monkeypatch.setattr(arxiv_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    client._last_request_at = 100.0

    client._wait_for_rate_limit()

    assert sleep_calls == [pytest.approx(2.0)]


def test_parse_search_response_fetches_root_entries_and_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_one = object()
    entry_two = object()
    calls: dict[str, object] = {}

    class FakeRoot:
        def findall(self, path: str, namespace: dict[str, str]) -> list[object]:
            calls["findall_path"] = path
            calls["findall_namespace"] = namespace
            return [entry_one, entry_two]

    def fake_fromstring(payload: str) -> FakeRoot:
        calls["payload"] = payload
        return FakeRoot()

    def fake_parse_entry(entry: object) -> ArxivPaperRecord:
        title = "first" if entry is entry_one else "second"
        return ArxivPaperRecord(
            paper_id=title,
            title=title,
            summary=title,
            published="p",
            updated="u",
            authors=[],
            categories=[],
            primary_category=None,
            comment=None,
            journal_reference=None,
            pdf_url=None,
            entry_url=None,
        )

    parse_int_values = {
        "opensearch:totalResults": 99,
        "opensearch:startIndex": 10,
        "opensearch:itemsPerPage": 2,
    }

    def fake_parse_int(_: object, path: str) -> int:
        return parse_int_values[path]

    monkeypatch.setattr(arxiv_module.DefusedElementTree, "fromstring", fake_fromstring)
    monkeypatch.setattr(ArxivClient, "_parse_entry", staticmethod(fake_parse_entry))
    monkeypatch.setattr(ArxivClient, "_parse_int", staticmethod(fake_parse_int))

    result = ArxivClient.parse_search_response("<feed />")

    assert calls["payload"] == "<feed />"
    assert calls["findall_path"] == "atom:entry"
    assert calls["findall_namespace"] == ATOM_NAMESPACE
    assert result.total_results == 99
    assert result.start_index == 10
    assert result.items_per_page == 2
    assert [paper.title for paper in result.papers] == ["first", "second"]


def test_parse_entry_returns_paper_record() -> None:
    root = DefusedElementTree.fromstring(SAMPLE_FEED)
    entry = root.find("atom:entry", ATOM_NAMESPACE)

    assert entry is not None

    record = ArxivClient._parse_entry(entry)

    assert record.paper_id == "http://arxiv.org/abs/cond-mat/0011267v1"
    assert record.title == "The electronic structure of cuprates from high energy spectroscopy"
    assert record.published == "2000-11-15T16:19:15Z"
    assert record.primary_category == "cond-mat.supr-con"


def test_read_text_returns_text_or_none() -> None:
    root = DefusedElementTree.fromstring(SAMPLE_FEED)

    assert ArxivClient._read_text(root, "opensearch:totalResults") == "184681"
    assert ArxivClient._read_text(root, "atom:missing") is None


def test_read_attribute_returns_value_or_none() -> None:
    root = DefusedElementTree.fromstring(SAMPLE_FEED)
    entry = root.find("atom:entry", ATOM_NAMESPACE)

    assert entry is not None

    assert (
        ArxivClient._read_attribute(entry, "arxiv:primary_category", "term") == "cond-mat.supr-con"
    )
    assert ArxivClient._read_attribute(entry, "arxiv:missing", "term") is None


def test_find_link_returns_matching_href_or_none() -> None:
    root = DefusedElementTree.fromstring(SAMPLE_FEED)
    entry = root.find("atom:entry", ATOM_NAMESPACE)

    assert entry is not None

    assert ArxivClient._find_link(entry, title="pdf") == "https://arxiv.org/pdf/cond-mat/0011267v1"
    assert (
        ArxivClient._find_link(entry, rel="alternate") == "https://arxiv.org/abs/cond-mat/0011267v1"
    )
    assert ArxivClient._find_link(entry, rel="missing") is None


def test_normalize_text_collapses_whitespace() -> None:
    assert ArxivClient._normalize_text("  graph\n  neural\t networks  ") == "graph neural networks"


def test_normalize_optional_text_handles_none_and_blank() -> None:
    assert ArxivClient._normalize_optional_text(None) is None
    assert ArxivClient._normalize_optional_text("   \n\t  ") is None
    assert ArxivClient._normalize_optional_text("  in\n press ") == "in press"
