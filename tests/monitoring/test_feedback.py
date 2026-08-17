"""Tests for user feedback submission handling."""

import pytest
from prometheus_client import REGISTRY

from agentic_paper_explorer.monitoring.feedback import InvalidFeedbackError, submit_feedback


def _feedback_value(rating: str) -> float:
    return REGISTRY.get_sample_value("rag_feedback_total", {"rating": rating}) or 0.0


def test_submit_feedback_records_rating() -> None:
    before = _feedback_value("up")

    submit_feedback(rating="up", query="What is retrieval?", comment="Clear answer")

    assert _feedback_value("up") == before + 1


def test_submit_feedback_rejects_unknown_rating() -> None:
    with pytest.raises(InvalidFeedbackError):
        submit_feedback(rating="sideways", query="What is retrieval?")


def test_submit_feedback_does_not_log_comment_text(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        submit_feedback(rating="down", query="What is retrieval?", comment="secret detail")

    assert "secret detail" not in caplog.text
    assert "has_comment=True" in caplog.text
