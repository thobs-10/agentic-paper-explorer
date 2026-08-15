"""Tests for the embedding model wrapper."""

import asyncio
from collections.abc import Iterator

import pytest

from agentic_paper_explorer.ingestion.processing import embeddings as embeddings_module
from agentic_paper_explorer.ingestion.processing.embeddings import embed_texts, get_embedding_model


class FakeHuggingFaceEmbeddings:
    def __init__(self, *, model_name: str) -> None:
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


@pytest.fixture(autouse=True)
def _clear_model_cache() -> Iterator[None]:
    get_embedding_model.cache_clear()
    yield
    get_embedding_model.cache_clear()


def test_get_embedding_model_returns_cached_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings_module, "HuggingFaceEmbeddings", FakeHuggingFaceEmbeddings)

    first = get_embedding_model("BAAI/bge-small-en-v1.5")
    second = get_embedding_model("BAAI/bge-small-en-v1.5")

    assert first is second
    assert first.model_name == "BAAI/bge-small-en-v1.5"


def test_embed_texts_returns_empty_list_for_no_texts() -> None:
    result = asyncio.run(embed_texts([], model_name="BAAI/bge-small-en-v1.5"))

    assert result == []


def test_embed_texts_offloads_to_thread_and_returns_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings_module, "HuggingFaceEmbeddings", FakeHuggingFaceEmbeddings)

    result = asyncio.run(embed_texts(["ab", "abcd"], model_name="BAAI/bge-small-en-v1.5"))

    assert result == [[2.0], [4.0]]
