"""Prefect orchestration over the ingestion pipeline.

Scheduled and batch runs go through `ingestion_flow` so each page's chunk, embed, and upsert steps
show up as task runs with their own duration, state, and retries in the Prefect UI. The on-demand
API endpoint keeps calling `pipeline.run_ingestion_pipeline` and needs no Prefect server.

The loop mirrors `run_ingestion_pipeline` on purpose: the step logic lives once in `pipeline.py`,
and only this short loop is repeated so neither path has to know about the other.
"""

from __future__ import annotations

from prefect import flow, task
from prefect.cache_policies import NO_CACHE

from agentic_paper_explorer.backend.database.qdrant_client import QdrantRepository
from agentic_paper_explorer.configs.settings import get_settings
from agentic_paper_explorer.ingestion import pipeline
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import (
    NEWEST_FIRST,
    ArxivPaperRecord,
)
from agentic_paper_explorer.ingestion.data_ingestion.batch_reader import iter_arxiv_papers
from agentic_paper_explorer.ingestion.pipeline import IngestionSummary
from agentic_paper_explorer.ingestion.processing.chunking import PaperChunk


# NO_CACHE: Prefect's default policy hashes task inputs, which is slow for embedding vectors and
# fails outright for the Qdrant client. Re-running a step is cheap and idempotent anyway.
@task(name="chunk-page", cache_policy=NO_CACHE)
def chunk_page_task(
    page: list[ArxivPaperRecord],
    *,
    max_characters: int,
    overlap_characters: int,
) -> list[PaperChunk]:
    return pipeline.chunk_page(
        page,
        max_characters=max_characters,
        overlap_characters=overlap_characters,
    )


@task(name="embed-chunks", cache_policy=NO_CACHE)
async def embed_chunks_task(
    chunks: list[PaperChunk],
    *,
    model_name: str,
) -> list[list[float]]:
    return await pipeline.embed_chunks(chunks, model_name=model_name)


# Only the upsert retries: arXiv fetching already retries in ArxivClient, and the embedding model
# runs in-process, so a failure there is not transient.
@task(name="upsert-chunks", cache_policy=NO_CACHE, retries=3, retry_delay_seconds=5)
async def upsert_chunks_task(
    repository: QdrantRepository,
    chunks: list[PaperChunk],
    vectors: list[list[float]],
    *,
    ensure_collection: bool,
) -> int:
    return await pipeline.upsert_chunks(
        repository, chunks, vectors, ensure_collection=ensure_collection
    )


@flow(name="arxiv-ingestion")
async def ingestion_flow(search_query: str, max_total_results: int | None = 10) -> IngestionSummary:
    """Fetch, chunk, embed, and store arXiv papers, with per-step task runs.

    `max_total_results` defaults to 10, matching the CLI, so an unbounded run is always explicit.
    """
    settings = get_settings()
    arxiv_client = pipeline.create_arxiv_client(settings)
    repository = pipeline.create_repository(settings)
    papers_processed: int = 0
    chunks_upserted: int = 0
    try:
        async for page in iter_arxiv_papers(
            arxiv_client,
            search_query=search_query,
            max_results_per_page=settings.arxiv_max_results_per_page,
            max_total_results=max_total_results,
            # Scheduled runs want what is new since the last run, not the same most-relevant hits.
            sort=NEWEST_FIRST,
        ):
            papers_processed += len(page)
            chunks = chunk_page_task(
                page,
                max_characters=settings.chunk_max_characters,
                overlap_characters=settings.chunk_overlap_characters,
            )
            if not chunks:
                continue
            vectors = await embed_chunks_task(chunks, model_name=settings.embedding_model_name)
            chunks_upserted += await upsert_chunks_task(
                repository, chunks, vectors, ensure_collection=chunks_upserted == 0
            )
    finally:
        arxiv_client.close()
        await repository.close()

    return IngestionSummary(papers_processed=papers_processed, chunks_upserted=chunks_upserted)
