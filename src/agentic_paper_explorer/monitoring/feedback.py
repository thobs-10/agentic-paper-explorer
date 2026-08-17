"""User feedback handling for answer quality signals."""

from __future__ import annotations

import logging

from agentic_paper_explorer.monitoring.metrics import FEEDBACK_RATINGS, record_feedback

logger = logging.getLogger(__name__)

_LOGGED_QUERY_CHARACTERS = 80


class InvalidFeedbackError(ValueError):
    """Raised when a feedback rating is outside the supported set."""


def submit_feedback(*, rating: str, query: str, comment: str | None = None) -> None:
    """Record a user rating for an answer and log the accompanying comment.

    Args:
        rating: Either `up` or `down`.
        query: The question the feedback refers to.
        comment: Optional free-text detail supplied by the user.

    Raises:
        InvalidFeedbackError: If `rating` is not a supported value.
    """
    if rating not in FEEDBACK_RATINGS:
        raise InvalidFeedbackError(f"Unsupported feedback rating: {rating}")

    record_feedback(rating)
    logger.info(
        "Feedback received rating=%s query=%r has_comment=%s",
        rating,
        query[:_LOGGED_QUERY_CHARACTERS],
        comment is not None,
    )
