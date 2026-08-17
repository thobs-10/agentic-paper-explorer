"""Tests for the frontend generation API client."""

import httpx
import pytest

from agentic_paper_explorer.frontend.client import (
    GenerationClient,
    GenerationClientError,
    _parse_sse_events,
)


def test_parse_sse_events_accumulates_partial_data() -> None:
    events = list(
        _parse_sse_events(
            iter(
                [
                    "event: start",
                    'data: {"query": "What is retrieval?"}',
                    "",
                    "event: chunk",
                    'data: {"text": "Grounded "}',
                    "",
                    "event: chunk",
                    'data: {"text": "answer [1]."}',
                    "",
                    "event: complete",
                    'data: {"sources": ["https://arxiv.org/abs/1"], "model": "test"}',
                    "",
                ]
            )
        )
    )

    assert [event.event for event in events] == ["start", "chunk", "chunk", "complete"]
    assert "".join(str(event.data.get("text", "")) for event in events) == "Grounded answer [1]."
    assert events[-1].data["sources"] == ["https://arxiv.org/abs/1"]


def test_parse_sse_events_rejects_non_object_data() -> None:
    with pytest.raises(GenerationClientError):
        list(_parse_sse_events(iter(["event: chunk", "data: []", ""])))


def test_generation_client_answer_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "http://localhost:8000/api/v1/generation/answer"),
        json={
            "query": "What is retrieval?",
            "answer": "Retrieval finds evidence [1].",
            "sources": ["https://arxiv.org/abs/1"],
            "model": "test-model",
        },
    )

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx, "post", fake_post)

    result = GenerationClient("http://localhost:8000").answer("What is retrieval?")

    assert result.answer == "Retrieval finds evidence [1]."
    assert result.sources == ["https://arxiv.org/abs/1"]
    assert result.model == "test-model"


def test_generation_client_stream_answer_parses_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    class StreamResponse:
        def __enter__(self) -> "StreamResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield "event: chunk"
            yield 'data: {"text": "partial"}'
            yield ""
            yield "event: complete"
            yield 'data: {"sources": [], "model": null}'
            yield ""

    def fake_stream(*args: object, **kwargs: object) -> StreamResponse:
        return StreamResponse()

    monkeypatch.setattr(httpx, "stream", fake_stream)

    events = list(GenerationClient("http://localhost:8000").stream_answer("Question"))

    assert events[0].data == {"text": "partial"}
    assert events[1].event == "complete"


def test_generation_client_keeps_sources_from_degraded_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            502,
            request=httpx.Request("POST", "http://localhost:8000/api/v1/generation/answer"),
            json={
                "query": "What is retrieval?",
                "answer": "I could not generate an answer right now.",
                "sources": ["https://arxiv.org/abs/1"],
                "model": "test-model",
                "degraded": True,
                "error_category": "rate_limit",
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = GenerationClient("http://localhost:8000").answer("What is retrieval?")

    assert result.degraded is True
    assert result.error_category == "rate_limit"
    assert result.sources == ["https://arxiv.org/abs/1"]


def test_generation_client_maps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            503,
            request=httpx.Request("POST", "http://localhost:8000/api/v1/generation/answer"),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(GenerationClientError):
        GenerationClient("http://localhost:8000").answer("Question")
