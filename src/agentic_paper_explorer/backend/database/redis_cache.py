"""Redis-backed cache adapter used by the retrieval layer."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, cast

from redis.asyncio import from_url

logger = logging.getLogger(__name__)


class RedisClientProtocol(Protocol):
    """Minimal async Redis client surface used by the cache adapter."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ex: int | None = None) -> Any: ...

    async def aclose(self) -> None: ...


class RedisCache:
    """JSON-serializing cache satisfying the retrieval `CacheProtocol`.

    Cache faults are treated as misses so retrieval degrades to vector search
    instead of failing the request.
    """

    def __init__(self, client: RedisClientProtocol) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> RedisCache:
        """Build a cache from a Redis connection URL."""
        # redis-py overloads get/set for both sync and async clients, so the async
        # client cannot structurally match an async-only protocol.
        return cls(cast(RedisClientProtocol, from_url(url, decode_responses=True)))

    async def get(self, key: str) -> Any | None:
        """Return the decoded cached value, or None on miss or fault."""
        try:
            raw = await self._client.get(key)
        except Exception:
            logger.warning("Redis cache read failed key=%s", key, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Discarding malformed Redis cache entry key=%s", key)
            return None

    async def set(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        """Store a JSON-serializable value, ignoring cache write faults."""
        try:
            payload = json.dumps(value)
        except (TypeError, ValueError):
            logger.warning("Skipping non-serializable Redis cache value key=%s", key)
            return
        try:
            await self._client.set(key, payload, ex=ttl)
        except Exception:
            logger.warning("Redis cache write failed key=%s", key, exc_info=True)

    async def close(self) -> None:
        """Release the underlying Redis connection."""
        await self._client.aclose()
