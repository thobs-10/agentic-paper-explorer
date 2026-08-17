"""Tests for the ingestion pipeline orchestration."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from agentic_paper_explorer.backend.database.qdrant_client import QdrantPoint
from agentic_paper_explorer.configs.settings import Settings
from agentic_paper_explorer.ingestion import pipeline as pipeline_module
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import ArxivPaperRecord
from agentic_paper_explorer.ingestion.processing.chunking import PaperChunk


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


class FakeQdrantRepository:
    def __init__(self, *, url: str, collection_name: str) -> None:
        self.url = url
        self.collection_name = collection_name
        self.ensure_collection_calls: list[int] = []
        self.upsert_points_calls: list[list[QdrantPoint]] = []
        self.closed = False

    async def ensure_collection(self, *, vector_size: int) -> None:
        self.ensure_collection_calls.append(vector_size)

    async def upsert_points(self, points: list[QdrantPoint]) -> None:
        self.upsert_points_calls.append(points)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _patch_pipeline_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "ArxivClient", FakeArxivClient)
    monkeypatch.setattr(pipeline_module, "QdrantRepository", FakeQdrantRepository)
    monkeypatch.setattr(pipeline_module, "get_settings", lambda: Settings(_env_file=None))


def _patch_pages(monkeypatch: pytest.MonkeyPatch, pages: list[list[ArxivPaperRecord]]) -> None:
    async def fake_iter_arxiv_papers(
        *_args: object, **_kwargs: object
    ) -> AsyncIterator[list[ArxivPaperRecord]]:
        for page in pages:
            yield page

    monkeypatch.setattr(pipeline_module, "iter_arxiv_papers", fake_iter_arxiv_papers)


def test_run_ingestion_pipeline_embeds_and_upserts_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pages(monkeypatch, [[_make_paper("p1"), _make_paper("p2")]])

    async def fake_embed_texts(texts: list[str], *, model_name: str) -> list[list[float]]:
        return [[float(index)] for index, _ in enumerate(texts)]

    monkeypatch.setattr(pipeline_module, "embed_texts", fake_embed_texts)

    summary = asyncio.run(pipeline_module.run_ingestion_pipeline("all:graph"))

    assert summary.papers_processed == 2
    assert summary.chunks_upserted == 2


def test_run_ingestion_pipeline_ensures_collection_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pages(monkeypatch, [[_make_paper("p1")], [_make_paper("p2")]])

    async def fake_embed_texts(texts: list[str], *, model_name: str) -> list[list[float]]:
        return [[1.0, 2.0] for _ in texts]

    monkeypatch.setattr(pipeline_module, "embed_texts", fake_embed_texts)

    repositories: list[FakeQdrantRepository] = []

    def tracking_repository(*, url: str, collection_name: str) -> FakeQdrantRepository:
        repository = FakeQdrantRepository(url=url, collection_name=collection_name)
        repositories.append(repository)
        return repository

    monkeypatch.setattr(pipeline_module, "QdrantRepository", tracking_repository)

    asyncio.run(pipeline_module.run_ingestion_pipeline("all:graph"))

    assert repositories[0].ensure_collection_calls == [2]
    assert len(repositories[0].upsert_points_calls) == 2


def test_run_ingestion_pipeline_closes_client_and_repository_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pages(monkeypatch, [[_make_paper("p1")]])

    async def failing_embed_texts(texts: list[str], *, model_name: str) -> list[list[float]]:
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(pipeline_module, "embed_texts", failing_embed_texts)

    created_clients: list[FakeArxivClient] = []
    created_repositories: list[FakeQdrantRepository] = []

    def tracking_arxiv_client(**kwargs: object) -> FakeArxivClient:
        client = FakeArxivClient(**kwargs)
        created_clients.append(client)
        return client

    def tracking_repository(*, url: str, collection_name: str) -> FakeQdrantRepository:
        repository = FakeQdrantRepository(url=url, collection_name=collection_name)
        created_repositories.append(repository)
        return repository

    monkeypatch.setattr(pipeline_module, "ArxivClient", tracking_arxiv_client)
    monkeypatch.setattr(pipeline_module, "QdrantRepository", tracking_repository)

    with pytest.raises(RuntimeError):
        asyncio.run(pipeline_module.run_ingestion_pipeline("all:graph"))

    assert created_clients[0].closed is True
    assert created_repositories[0].closed is True


def test_chunk_point_id_is_deterministic() -> None:
    chunk = PaperChunk(
        paper_id="paper-1",
        chunk_index=0,
        text="text",
        title="title",
        authors=[],
        categories=[],
        published="2026-01-01T00:00:00Z",
        pdf_url=None,
        entry_url=None,
    )

    first = pipeline_module._chunk_point_id(chunk)
    second = pipeline_module._chunk_point_id(chunk)

    assert first == second


def test_chunk_payload_includes_expected_fields() -> None:
    chunk = PaperChunk(
        paper_id="paper-1",
        chunk_index=2,
        text="text",
        title="title",
        authors=["Author"],
        categories=["cs.AI"],
        published="2026-01-01T00:00:00Z",
        pdf_url="https://arxiv.org/pdf/paper-1",
        entry_url="https://arxiv.org/abs/paper-1",
    )

    payload = pipeline_module._chunk_payload(chunk)

    assert payload == {
        "paper_id": "paper-1",
        "chunk_index": 2,
        "text": "text",
        "title": "title",
        "authors": ["Author"],
        "categories": ["cs.AI"],
        "published": "2026-01-01T00:00:00Z",
        "pdf_url": "https://arxiv.org/pdf/paper-1",
        "entry_url": "https://arxiv.org/abs/paper-1",
    }


def test_main_runs_pipeline_for_query(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_run_ingestion_pipeline(
        search_query: str, *, max_total_results: int | None = None
    ) -> object:
        assert search_query == "all:transformer"
        assert max_total_results == 5
        return pipeline_module.IngestionSummary(papers_processed=7, chunks_upserted=21)

    monkeypatch.setattr(pipeline_module, "run_ingestion_pipeline", fake_run_ingestion_pipeline)
    monkeypatch.setattr("sys.argv", ["pipeline.py", "all:transformer", "--max-results", "5"])

    exit_code = pipeline_module.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Processed 7 papers" in captured.out
    assert "21 chunks" in captured.out


def test_main_uses_safe_default_max_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_run_ingestion_pipeline(
        search_query: str, *, max_total_results: int | None = None
    ) -> object:
        assert search_query == "all:transformer"
        assert max_total_results == 10
        return pipeline_module.IngestionSummary(papers_processed=2, chunks_upserted=4)

    monkeypatch.setattr(pipeline_module, "run_ingestion_pipeline", fake_run_ingestion_pipeline)
    monkeypatch.setattr("sys.argv", ["pipeline.py", "all:transformer"])

    exit_code = pipeline_module.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Processed 2 papers" in captured.out
    assert "4 chunks" in captured.out
