"""Tests for the feedback endpoint and the metrics exposition route."""

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from agentic_paper_explorer.backend.api.router import app


def _feedback_value(rating: str) -> float:
    return REGISTRY.get_sample_value("rag_feedback_total", {"rating": rating}) or 0.0


def test_feedback_route_records_rating() -> None:
    before = _feedback_value("up")
    client = TestClient(app)

    response = client.post(
        "/api/v1/feedback",
        json={"query": "What is retrieval?", "rating": "up", "comment": "Useful"},
    )

    assert response.status_code == 201
    assert response.json() == {"status": "recorded", "rating": "up"}
    assert _feedback_value("up") == before + 1


def test_feedback_route_rejects_unknown_rating() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/feedback",
        json={"query": "What is retrieval?", "rating": "sideways"},
    )

    assert response.status_code == 422


def test_metrics_route_exposes_custom_collectors() -> None:
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "rag_feedback_total" in response.text
    assert "rag_answer_requests_total" in response.text
