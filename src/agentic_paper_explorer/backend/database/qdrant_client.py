"""Qdrant vector store wrapper used by the ingestion pipeline and retrieval layer."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams


@dataclass(slots=True, frozen=True)
class QdrantPoint:
    """A single vector point to store in Qdrant, decoupled from any caller's domain model."""

    point_id: str | int | UUID
    vector: list[float]
    payload: dict[str, object]


class QdrantRepository:
    """Thin async wrapper around Qdrant for collection setup and point upserts."""

    def __init__(
        self,
        url: str,
        collection_name: str,
    ) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection_name = collection_name

    async def ensure_collection(self, vector_size: int) -> None:
        """Create the collection if it does not already exist (idempotent).

        Args:
            vector_size: The dimensionality of the vectors to be stored in the collection.
        """
        if await self._client.collection_exists(self._collection_name):
            return
        await self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    async def upsert_points(self, points: list[QdrantPoint]) -> None:
        """Upsert points into the collection. Callers should use deterministic
        `point_id`s so repeated ingestion updates rather than duplicates.

        Args:
            points: A list of `QdrantPoint` objects to upsert into the collection.
        """
        if not points:
            return

        def _coerce_point_id(point_id: str | int | UUID) -> str | int | UUID:
            if isinstance(point_id, int):
                return point_id
            if isinstance(point_id, UUID):
                return point_id
            try:
                return UUID(str(point_id))
            except ValueError as exc:
                raise ValueError(
                    f"Qdrant point IDs must be UUIDs or integers; received {point_id!r}."
                ) from exc

        await self._client.upsert(
            collection_name=self._collection_name,
            points=[
                PointStruct(
                    id=_coerce_point_id(point.point_id),
                    vector=point.vector,
                    payload=point.payload,
                )
                for point in points
            ],
        )

    async def close(self) -> None:
        """Release the underlying Qdrant connection."""
        await self._client.close()
