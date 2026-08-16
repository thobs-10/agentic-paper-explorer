"""Tests for the Redis-backed retrieval cache adapter."""

import asyncio
import json

from agentic_paper_explorer.backend.database.redis_cache import RedisCache


class FakeRedis:
    """Minimal async Redis stand-in with optional fault injection."""

    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}
        self.closed = False
        self._fail = fail

    async def get(self, key: str) -> str | None:
        if self._fail:
            raise ConnectionError("redis unavailable")
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self._fail:
            raise ConnectionError("redis unavailable")
        self.store[key] = value
        self.expiries[key] = ex

    async def aclose(self) -> None:
        self.closed = True


def test_set_then_get_round_trips_json_value() -> None:
    client = FakeRedis()
    cache = RedisCache(client)

    async def scenario() -> object | None:
        await cache.set("prompt:retrieval", {"chunks": [{"paper_id": "p1"}]}, ttl=60)
        return await cache.get("prompt:retrieval")

    value = asyncio.run(scenario())

    assert value == {"chunks": [{"paper_id": "p1"}]}
    assert client.expiries["prompt:retrieval"] == 60


def test_get_returns_none_on_cache_miss() -> None:
    cache = RedisCache(FakeRedis())

    assert asyncio.run(cache.get("prompt:absent")) is None


def test_get_returns_none_when_redis_read_fails() -> None:
    cache = RedisCache(FakeRedis(fail=True))

    assert asyncio.run(cache.get("prompt:retrieval")) is None


def test_get_discards_malformed_cache_entry() -> None:
    client = FakeRedis()
    client.store["prompt:retrieval"] = "{not valid json"
    cache = RedisCache(client)

    assert asyncio.run(cache.get("prompt:retrieval")) is None


def test_set_swallows_redis_write_failure() -> None:
    cache = RedisCache(FakeRedis(fail=True))

    asyncio.run(cache.set("prompt:retrieval", {"chunks": []}, ttl=60))


def test_set_skips_non_serializable_value() -> None:
    client = FakeRedis()
    cache = RedisCache(client)

    asyncio.run(cache.set("prompt:retrieval", {"chunks": {object()}}))

    assert client.store == {}


def test_set_without_ttl_stores_value_without_expiry() -> None:
    client = FakeRedis()
    cache = RedisCache(client)

    asyncio.run(cache.set("prompt:retrieval", {"chunks": []}))

    assert json.loads(client.store["prompt:retrieval"]) == {"chunks": []}
    assert client.expiries["prompt:retrieval"] is None


def test_close_releases_client() -> None:
    client = FakeRedis()
    cache = RedisCache(client)

    asyncio.run(cache.close())

    assert client.closed is True
