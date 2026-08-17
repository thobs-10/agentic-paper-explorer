"""Tests for the Prometheus metric recording helpers."""

from prometheus_client import REGISTRY

from agentic_paper_explorer.monitoring import metrics


def _counter_value(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(f"{name}_total", labels) or 0.0


def test_record_answer_counts_successful_outcome() -> None:
    labels = {"endpoint": "answer", "outcome": "ok"}
    before = _counter_value("rag_answer_requests", labels)

    metrics.record_answer("answer", degraded=False)

    assert _counter_value("rag_answer_requests", labels) == before + 1


def test_record_answer_counts_degraded_outcome_and_error_category() -> None:
    outcome_labels = {"endpoint": "stream", "outcome": "degraded"}
    error_labels = {"category": "timeout"}
    outcome_before = _counter_value("rag_answer_requests", outcome_labels)
    error_before = _counter_value("rag_llm_errors", error_labels)

    metrics.record_answer("stream", degraded=True, error_category="timeout")

    assert _counter_value("rag_answer_requests", outcome_labels) == outcome_before + 1
    assert _counter_value("rag_llm_errors", error_labels) == error_before + 1


def test_record_retrieval_tracks_chunk_count_and_cache_result() -> None:
    cache_labels = {"result": "hit"}
    cache_before = _counter_value("rag_retrieval_cache", cache_labels)
    observations_before = REGISTRY.get_sample_value("rag_retrieval_chunks_count") or 0.0
    total_before = REGISTRY.get_sample_value("rag_retrieval_chunks_sum") or 0.0

    metrics.record_retrieval(chunk_count=3, cached=True)

    assert _counter_value("rag_retrieval_cache", cache_labels) == cache_before + 1
    assert REGISTRY.get_sample_value("rag_retrieval_chunks_count") == observations_before + 1
    assert REGISTRY.get_sample_value("rag_retrieval_chunks_sum") == total_before + 3


def test_record_feedback_counts_rating() -> None:
    labels = {"rating": "down"}
    before = _counter_value("rag_feedback", labels)

    metrics.record_feedback("down")

    assert _counter_value("rag_feedback", labels) == before + 1
