"""Tests for the ingestion API health endpoint."""

from fastapi.testclient import TestClient

from agentic_paper_explorer.ingestion.api.router import app


def test_health_endpoint_reports_ingestion_service() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ingestion"}
