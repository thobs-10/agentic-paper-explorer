"""Tests for the Prefect orchestration over the ingestion pipeline."""

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from prefect.testing.utilities import prefect_test_harness

from agentic_paper_explorer.backend.database.qdrant_client import QdrantPoint
from agentic_paper_explorer.configs.settings import Settings
from agentic_paper_explorer.ingestion import flows as flows_module
from agentic_paper_explorer.ingestion import pipeline as pipeline_module
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import (
    NEWEST_FIRST,
    ArxivPaperRecord,
)
from agentic_paper_explorer.ingestion.pipeline import IngestionSummary


def _make_paper(paper_id: str) -> ArxivPaperRecord:
    return ArxivPaperRecord(
        paper_id=paper_id,
        title=f"Title {paper_id}",
        summary="An abstract.",
        published="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        authors=["Author"],
        categories=["cs.AI"],
        primary_category="cs.AI",
        comment=None,
        journal_reference=None,
        pdf_url=f"https://arxiv.org/pdf/{paper_id}",
        entry_url=f"https://arxiv.org/abs/{paper_id}",
    )


class FakeArxivClient:
    def __init__(self, **kwargs: object) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FlakyQdrantRepository:
    """Fails the first `failures` upserts, then succeeds."""

    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.upsert_attempts: list[list[QdrantPoint]] = []
        self.closed = False

    async def ensure_collection(self, *, vector_size: int) -> None:
        return None

    async def upsert_points(self, points: list[QdrantPoint]) -> None:
        self.upsert_attempts.append(points)
        if len(self.upsert_attempts) <= self.failures:
            raise ConnectionError("qdrant unavailable")

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True, scope="module")
def _prefect_backend() -> Iterator[None]:
    # Temporary in-process API and SQLite DB, so tests need no running Prefect server.
    with prefect_test_harness():
        yield


@pytest.fixture(autouse=True)
def _patch_pipeline_collaborators(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Patch the flow's collaborators and return the recorded `iter_arxiv_papers` kwargs."""
    iter_calls: list[dict[str, object]] = []

    async def fake_iter_arxiv_papers(
        *_args: object, **kwargs: object
    ) -> AsyncIterator[list[ArxivPaperRecord]]:
        iter_calls.append(kwargs)
        yield [_make_paper("p1"), _make_paper("p2")]

    async def fake_embed_texts(texts: list[str], *, model_name: str) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(pipeline_module, "ArxivClient", FakeArxivClient)
    monkeypatch.setattr(flows_module, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(flows_module, "iter_arxiv_papers", fake_iter_arxiv_papers)
    monkeypatch.setattr(pipeline_module, "embed_texts", fake_embed_texts)
    # Keep retry tests fast; the retry count under test stays the production value.
    monkeypatch.setattr(
        flows_module,
        "upsert_chunks_task",
        flows_module.upsert_chunks_task.with_options(retry_delay_seconds=0),
    )
    return iter_calls


def _use_repository(
    monkeypatch: pytest.MonkeyPatch, repository: FlakyQdrantRepository
) -> FlakyQdrantRepository:
    monkeypatch.setattr(pipeline_module, "QdrantRepository", lambda **_kwargs: repository)
    return repository


def test_ingestion_flow_returns_pipeline_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _use_repository(monkeypatch, FlakyQdrantRepository())

    summary = asyncio.run(flows_module.ingestion_flow("all:graph"))

    assert summary == IngestionSummary(papers_processed=2, chunks_upserted=2)
    assert repository.closed is True


def test_ingestion_flow_retries_transient_upsert_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _use_repository(monkeypatch, FlakyQdrantRepository(failures=1))

    summary = asyncio.run(flows_module.ingestion_flow("all:graph"))

    assert summary.chunks_upserted == 2
    assert len(repository.upsert_attempts) == 2


def test_ingestion_flow_fails_after_upsert_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _use_repository(monkeypatch, FlakyQdrantRepository(failures=10))

    with pytest.raises(ConnectionError):
        asyncio.run(flows_module.ingestion_flow("all:graph"))

    # One attempt plus the three configured retries.
    assert len(repository.upsert_attempts) == 4
    assert repository.closed is True


def test_ingestion_flow_does_not_retry_embedding_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_repository(monkeypatch, FlakyQdrantRepository())
    embed_calls: list[int] = []

    async def failing_embed_texts(texts: list[str], *, model_name: str) -> list[list[float]]:
        embed_calls.append(len(texts))
        raise RuntimeError("model failed to load")

    monkeypatch.setattr(pipeline_module, "embed_texts", failing_embed_texts)

    with pytest.raises(RuntimeError):
        asyncio.run(flows_module.ingestion_flow("all:graph"))

    assert len(embed_calls) == 1


def test_ingestion_flow_fetches_newest_papers_first(
    monkeypatch: pytest.MonkeyPatch, _patch_pipeline_collaborators: list[dict[str, object]]
) -> None:
    _use_repository(monkeypatch, FlakyQdrantRepository())

    asyncio.run(flows_module.ingestion_flow("all:graph", max_total_results=3))

    assert _patch_pipeline_collaborators[0]["sort"] == NEWEST_FIRST
    assert _patch_pipeline_collaborators[0]["max_total_results"] == 3
