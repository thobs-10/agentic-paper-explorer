"""Embedding model loading and inference for ingestion chunks."""

from __future__ import annotations

import asyncio
from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings


@lru_cache
def get_embedding_model(model_name: str) -> HuggingFaceEmbeddings:
    """Return a process-wide cached embedding model instance for `model_name`.
    Args:
        model_name: The name of the embedding model to load.

    Returns:
        An instance of `HuggingFaceEmbeddings` corresponding to `model_name`.
    """
    return HuggingFaceEmbeddings(model_name=model_name)


async def embed_texts(
    texts: list[str],
    *,
    model_name: str,
) -> list[list[float]]:
    """Embed a batch of texts, offloading the CPU-bound work off the event loop.

    Args:
        texts: A list of texts to embed.
        model_name: The name of the embedding model to use.

    Returns:
        A list of embeddings, one per input text.
    """
    if not texts:
        return []
    model = get_embedding_model(model_name)
    return await asyncio.to_thread(model.embed_documents, texts)


async def embed_query(text: str, *, model_name: str) -> list[float]:
    """Embed a single search query using the query-side encoder.

    Args:
        text: The query text to embed.
        model_name: The name of the embedding model to use.

    Returns:
        The query embedding vector.
    """
    model = get_embedding_model(model_name)
    return await asyncio.to_thread(model.embed_query, text)
