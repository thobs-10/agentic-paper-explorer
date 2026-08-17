"""Prometheus metric definitions and FastAPI instrumentation helpers.

This module is the single place that touches `prometheus_client`, so the rest of
the codebase records telemetry through small, typed functions instead of holding
references to collector objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram

if TYPE_CHECKING:
    from fastapi import FastAPI

METRICS_ENDPOINT = "/metrics"

ANSWER_OUTCOMES = ("ok", "degraded")
CACHE_RESULTS = ("hit", "miss")
FEEDBACK_RATINGS = ("up", "down")

answer_requests_total = Counter(
    "rag_answer_requests_total",
    "Answer requests grouped by endpoint and outcome.",
    labelnames=("endpoint", "outcome"),
)

retrieval_chunks = Histogram(
    "rag_retrieval_chunks",
    "Number of context chunks returned per retrieval call.",
    buckets=(0, 1, 2, 3, 5, 8, 13),
)

retrieval_cache_total = Counter(
    "rag_retrieval_cache_total",
    "Retrieval cache lookups grouped by result.",
    labelnames=("result",),
)

llm_errors_total = Counter(
    "rag_llm_errors_total",
    "Generation failures grouped by normalized provider error category.",
    labelnames=("category",),
)

feedback_total = Counter(
    "rag_feedback_total",
    "User feedback submissions grouped by rating.",
    labelnames=("rating",),
)


def _initialize_label_values() -> None:
    """Create zero-valued series so dashboards render before the first event."""
    for endpoint in ("answer", "stream"):
        for outcome in ANSWER_OUTCOMES:
            answer_requests_total.labels(endpoint=endpoint, outcome=outcome)
    for result in CACHE_RESULTS:
        retrieval_cache_total.labels(result=result)
    for rating in FEEDBACK_RATINGS:
        feedback_total.labels(rating=rating)


def record_answer(endpoint: str, *, degraded: bool, error_category: str | None = None) -> None:
    """Record the outcome of one answer request and any provider error category."""
    outcome = "degraded" if degraded else "ok"
    answer_requests_total.labels(endpoint=endpoint, outcome=outcome).inc()
    if error_category:
        llm_errors_total.labels(category=error_category).inc()


def record_retrieval(*, chunk_count: int, cached: bool) -> None:
    """Record how much context a retrieval call returned and whether it was cached."""
    retrieval_chunks.observe(chunk_count)
    retrieval_cache_total.labels(result="hit" if cached else "miss").inc()


def record_feedback(rating: str) -> None:
    """Record one user feedback submission."""
    feedback_total.labels(rating=rating).inc()


def setup_metrics(app: FastAPI) -> None:
    """Expose default HTTP metrics plus the custom collectors on `/metrics`."""
    from prometheus_fastapi_instrumentator import Instrumentator

    _initialize_label_values()
    Instrumentator(
        excluded_handlers=[METRICS_ENDPOINT, "/health"],
        should_group_status_codes=False,
    ).instrument(app).expose(app, endpoint=METRICS_ENDPOINT, include_in_schema=False)
