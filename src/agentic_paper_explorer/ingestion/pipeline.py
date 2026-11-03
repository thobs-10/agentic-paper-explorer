"""Ingestion pipeline: fetch arXiv metadata, chunk, embed, and store in Qdrant."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from agentic_paper_explorer.backend.database.qdrant_client import QdrantPoint, QdrantRepository
from agentic_paper_explorer.configs.settings import Settings, get_settings
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import (
    ArxivClient,
    ArxivPaperRecord,
)
from agentic_paper_explorer.ingestion.data_ingestion.batch_reader import iter_arxiv_papers
from agentic_paper_explorer.ingestion.processing.chunking import PaperChunk, chunk_paper
from agentic_paper_explorer.ingestion.processing.embeddings import embed_texts


@dataclass(slots=True, frozen=True)
class IngestionSummary:
    """Outcome counters for a single ingestion pipeline run."""

    papers_processed: int
    chunks_upserted: int


class ChunkStep(Protocol):
    def __call__(
        self,
        page: list[ArxivPaperRecord],
        *,
        max_characters: int,
        overlap_characters: int,
    ) -> list[PaperChunk]: ...


class EmbedStep(Protocol):
    def __call__(
        self, chunks: list[PaperChunk], *, model_name: str
    ) -> Awaitable[list[list[float]]]: ...


class UpsertStep(Protocol):
    def __call__(
        self,
        repository: QdrantRepository,
        chunks: list[PaperChunk],
        vectors: list[list[float]],
        *,
        ensure_collection: bool,
    ) -> Awaitable[int]: ...


@dataclass(slots=True, frozen=True)
class PipelineSteps:
    """Per-page steps of the pipeline.

    The defaults are plain functions. The Prefect flow passes task-wrapped versions of the same
    functions, so on-demand API runs and orchestrated runs share one loop and cannot drift apart.
    """

    chunk: ChunkStep
    embed: EmbedStep
    upsert: UpsertStep


def chunk_page(
    page: list[ArxivPaperRecord],
    *,
    max_characters: int,
    overlap_characters: int,
) -> list[PaperChunk]:
    """Split every paper on a page into embedding-sized chunks."""
    return [
        chunk
        for paper in page
        for chunk in chunk_paper(
            paper, max_characters=max_characters, overlap_characters=overlap_characters
        )
    ]


async def embed_chunks(chunks: list[PaperChunk], *, model_name: str) -> list[list[float]]:
    """Embed the text of each chunk, preserving order."""
    return await embed_texts([chunk.text for chunk in chunks], model_name=model_name)


async def upsert_chunks(
    repository: QdrantRepository,
    chunks: list[PaperChunk],
    vectors: list[list[float]],
    *,
    ensure_collection: bool,
) -> int:
    """Store chunks with their vectors and return how many points were upserted.

    Safe to retry: `ensure_collection` is idempotent and point IDs are deterministic.
    """
    if ensure_collection:
        await repository.ensure_collection(vector_size=len(vectors[0]))
    points = [
        QdrantPoint(point_id=_chunk_point_id(chunk), vector=vector, payload=_chunk_payload(chunk))
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    await repository.upsert_points(points)
    return len(points)


def default_steps() -> PipelineSteps:
    """Plain, non-orchestrated pipeline steps."""
    return PipelineSteps(chunk=chunk_page, embed=embed_chunks, upsert=upsert_chunks)


async def run_ingestion_pipeline(
    search_query: str,
    *,
    max_total_results: int | None = None,
    steps: PipelineSteps | None = None,
) -> IngestionSummary:
    """Fetch, chunk, embed, and store arXiv papers for a search query."""
    settings = get_settings()
    arxiv_client = _create_arxiv_client(settings)
    repository = QdrantRepository(
        url=settings.qdrant_url, collection_name=settings.qdrant_collection_name
    )
    try:
        return await _ingest_pages(
            arxiv_client,
            repository,
            settings,
            search_query=search_query,
            max_total_results=max_total_results,
            steps=steps or default_steps(),
        )
    finally:
        arxiv_client.close()
        await repository.close()


async def _ingest_pages(
    arxiv_client: ArxivClient,
    repository: QdrantRepository,
    settings: Settings,
    *,
    search_query: str,
    max_total_results: int | None,
    steps: PipelineSteps,
) -> IngestionSummary:
    """Run the chunk, embed, and upsert steps over every fetched page."""
    papers_processed = 0
    chunks_upserted = 0
    collection_ready = False

    async for page in iter_arxiv_papers(
        arxiv_client,
        search_query=search_query,
        max_results_per_page=settings.arxiv_max_results_per_page,
        max_total_results=max_total_results,
    ):
        papers_processed += len(page)
        chunks = steps.chunk(
            page,
            max_characters=settings.chunk_max_characters,
            overlap_characters=settings.chunk_overlap_characters,
        )
        if not chunks:
            continue
        vectors = await steps.embed(chunks, model_name=settings.embedding_model_name)
        chunks_upserted += await steps.upsert(
            repository, chunks, vectors, ensure_collection=not collection_ready
        )
        collection_ready = True

    return IngestionSummary(papers_processed=papers_processed, chunks_upserted=chunks_upserted)


def _create_arxiv_client(settings: Settings) -> ArxivClient:
    return ArxivClient(
        base_url=settings.arxiv_base_url,
        timeout_seconds=settings.arxiv_timeout_seconds,
        max_retries=settings.arxiv_max_retries,
        retry_backoff_seconds=settings.arxiv_retry_backoff_seconds,
        min_request_interval_seconds=settings.arxiv_min_request_interval_seconds,
    )


def _chunk_point_id(chunk: PaperChunk) -> UUID:
    """Build a deterministic point ID so re-ingestion upserts instead of duplicating."""
    return uuid5(NAMESPACE_URL, f"{chunk.paper_id}:{chunk.chunk_index}")


def _chunk_payload(chunk: PaperChunk) -> dict[str, object]:
    """Build the Qdrant payload carrying chunk text and paper metadata."""
    return {
        "paper_id": chunk.paper_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "title": chunk.title,
        "authors": chunk.authors,
        "categories": chunk.categories,
        "published": chunk.published,
        "pdf_url": chunk.pdf_url,
        "entry_url": chunk.entry_url,
    }


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and execute a bounded ingestion pipeline run."""
    parser = argparse.ArgumentParser(
        description="Fetch arXiv papers, chunk them, embed them, and store them in Qdrant."
    )
    parser.add_argument(
        "search_query", nargs="?", help="The arXiv search query, for example: all:transformer"
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Cap on the number of papers to process across all pages. Defaults to 10 for CLI safety.",
    )
    args = parser.parse_args(argv)

    if not args.search_query:
        parser.print_usage(sys.stderr)
        print("error: a search query is required", file=sys.stderr)
        return 2

    summary = asyncio.run(
        run_ingestion_pipeline(args.search_query, max_total_results=args.max_results)
    )
    print(
        f"Processed {summary.papers_processed} papers and upserted {summary.chunks_upserted} chunks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
