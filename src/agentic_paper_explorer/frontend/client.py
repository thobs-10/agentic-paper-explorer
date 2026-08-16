"""HTTP client for the grounded generation API."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx


class GenerationClientError(RuntimeError):
    """Raised when the generation API cannot return a valid response."""


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    """Complete response returned by the non-streaming generation endpoint."""

    query: str
    answer: str
    sources: list[str]
    model: str | None


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One parsed Server-Sent Event from the streaming endpoint."""

    event: str
    data: dict[str, Any]


class GenerationClient:
    """Synchronous client for the backend generation endpoints."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)

    def answer(self, query: str) -> GenerationResponse:
        """Return one complete grounded answer."""
        try:
            response = httpx.post(
                f"{self._base_url}/api/v1/generation/answer",
                json={"query": query},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GenerationClientError("The generation service could not be reached.") from exc
        return _parse_response(payload)

    def stream_answer(self, query: str) -> Iterator[StreamEvent]:
        """Yield parsed events from the Server-Sent Events endpoint."""
        try:
            with httpx.stream(
                "POST",
                f"{self._base_url}/api/v1/generation/answer/stream",
                json={"query": query},
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                yield from _parse_sse_events(response.iter_lines())
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise GenerationClientError("The streaming service could not be reached.") from exc


def _parse_response(payload: object) -> GenerationResponse:
    if not isinstance(payload, dict):
        raise GenerationClientError("The generation service returned an invalid response.")
    try:
        return GenerationResponse(
            query=str(payload["query"]),
            answer=str(payload["answer"]),
            sources=[str(source) for source in payload.get("sources", [])],
            model=str(payload["model"]) if payload.get("model") is not None else None,
        )
    except (KeyError, TypeError) as exc:
        raise GenerationClientError("The generation service returned an invalid response.") from exc


def _parse_sse_events(lines: Iterator[str]) -> Iterator[StreamEvent]:
    event_name = "message"
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
        elif not line and data_lines:
            payload = json.loads("\n".join(data_lines))
            if not isinstance(payload, dict):
                raise GenerationClientError("The streaming service returned invalid event data.")
            yield StreamEvent(event=event_name, data=payload)
            event_name = "message"
            data_lines = []
    if data_lines:
        payload = json.loads("\n".join(data_lines))
        if not isinstance(payload, dict):
            raise GenerationClientError("The streaming service returned invalid event data.")
        yield StreamEvent(event=event_name, data=payload)
