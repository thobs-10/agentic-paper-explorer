"""Tests for the Qdrant repository wrapper."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from qdrant_client import AsyncQdrantClient

from agentic_paper_explorer.backend.database import qdrant_client as qdrant_module
from agentic_paper_explorer.backend.database.qdrant_client import QdrantPoint, QdrantRepository


class FakeAsyncQdrantClient:
    def __init__(self, *, url: str) -> None:
        self.url = url
        self.collection_exists_result = False
        self.create_collection_calls: list[dict[str, object]] = []
        self.upsert_calls: list[dict[str, object]] = []
        self.closed = False

    async def collection_exists(self, collection_name: str) -> bool:
        self.checked_collection_name = collection_name
        return self.collection_exists_result

    async def create_collection(self, *, collection_name: str, vectors_config: object) -> None:
        self.create_collection_calls.append(
            {"collection_name": collection_name, "vectors_config": vectors_config}
        )

    async def upsert(self, *, collection_name: str, points: list[object]) -> None:
        self.upsert_calls.append({"collection_name": collection_name, "points": points})

    async def close(self) -> None:
        self.closed = True


def _make_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[QdrantRepository, FakeAsyncQdrantClient]:
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", FakeAsyncQdrantClient)
    repository = QdrantRepository(url="http://localhost:6333", collection_name="arxiv_papers")
    fake_client: FakeAsyncQdrantClient = repository._client  # type: ignore[assignment]
    return repository, fake_client


def test_ensure_collection_skips_creation_when_it_already_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, fake_client = _make_repository(monkeypatch)
    fake_client.collection_exists_result = True

    asyncio.run(repository.ensure_collection(vector_size=384))

    assert fake_client.checked_collection_name == "arxiv_papers"
    assert fake_client.create_collection_calls == []


def test_ensure_collection_creates_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    repository, fake_client = _make_repository(monkeypatch)
    fake_client.collection_exists_result = False

    asyncio.run(repository.ensure_collection(vector_size=384))

    assert len(fake_client.create_collection_calls) == 1
    call = fake_client.create_collection_calls[0]
    assert call["collection_name"] == "arxiv_papers"
    assert call["vectors_config"].size == 384  # type: ignore[attr-defined]


def test_upsert_points_skips_call_when_no_points(monkeypatch: pytest.MonkeyPatch) -> None:
    repository, fake_client = _make_repository(monkeypatch)

    asyncio.run(repository.upsert_points([]))

    assert fake_client.upsert_calls == []


def test_upsert_points_builds_point_structs(monkeypatch: pytest.MonkeyPatch) -> None:
    repository, fake_client = _make_repository(monkeypatch)
    point_id = UUID("12345678-1234-4234-8234-123456789abc")
    points = [
        QdrantPoint(point_id=point_id, vector=[0.1, 0.2], payload={"paper_id": "paper-1"}),
    ]

    asyncio.run(repository.upsert_points(points))

    assert len(fake_client.upsert_calls) == 1
    call = fake_client.upsert_calls[0]
    assert call["collection_name"] == "arxiv_papers"
    upserted_point = call["points"][0]  # type: ignore[index]
    assert upserted_point.id == point_id
    assert upserted_point.vector == [0.1, 0.2]
    assert upserted_point.payload == {"paper_id": "paper-1"}


def test_close_closes_underlying_client(monkeypatch: pytest.MonkeyPatch) -> None:
    repository, fake_client = _make_repository(monkeypatch)

    asyncio.run(repository.close())

    assert fake_client.closed is True


def _check_qdrant_running(url: str) -> bool:
    try:
        response = httpx.get(f"{url}/collections", timeout=1.5)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@pytest.mark.skipif(
    not _check_qdrant_running("http://localhost:6333"),
    reason="Qdrant container is not running on localhost:6333",
)
def test_repository_upserts_points_to_running_qdrant_container() -> None:
    collection_name = f"integration-test-{uuid4().hex}"
    repository = QdrantRepository(url="http://localhost:6333", collection_name=collection_name)
    client = AsyncQdrantClient(url="http://localhost:6333")

    try:
        asyncio.run(repository.ensure_collection(vector_size=3))
        asyncio.run(
            repository.upsert_points(
                [
                    QdrantPoint(
                        point_id=uuid4(),
                        vector=[0.1, 0.2, 0.3],
                        payload={"paper_id": "paper-1", "title": "Integration test"},
                    )
                ]
            )
        )
        assert asyncio.run(client.collection_exists(collection_name)) is True
        count_result = asyncio.run(client.count(collection_name=collection_name))
        assert count_result.count == 1
    finally:
        asyncio.run(repository.close())
        asyncio.run(client.close())
