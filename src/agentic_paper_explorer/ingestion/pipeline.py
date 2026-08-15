"""Ingestion pipeline: fetch arXiv metadata, chunk, embed, and store in Qdrant."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from agentic_paper_explorer.backend.database.qdrant_client import QdrantPoint, QdrantRepository
from agentic_paper_explorer.configs.settings import get_settings
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import ArxivClient
from agentic_paper_explorer.ingestion.data_ingestion.batch_reader import iter_arxiv_papers
from agentic_paper_explorer.ingestion.processing.chunking import PaperChunk, chunk_paper
from agentic_paper_explorer.ingestion.processing.embeddings import embed_texts


@dataclass(slots=True, frozen=True)
class IngestionSummary:
    """Outcome counters for a single ingestion pipeline run."""

    papers_processed: int
    chunks_upserted: int


async def run_ingestion_pipeline(
    search_query: str,
    *,
    max_total_results: int | None = None,
) -> IngestionSummary:
    """Fetch, chunk, embed, and store arXiv papers for a search query."""
    # Load settings and initialize collaborators
    settings = get_settings()
    # Initialize the ArxivClient and QdrantRepository with settings
    arxiv_client = ArxivClient(
        base_url=settings.arxiv_base_url,
        timeout_seconds=settings.arxiv_timeout_seconds,
        max_retries=settings.arxiv_max_retries,
        retry_backoff_seconds=settings.arxiv_retry_backoff_seconds,
        min_request_interval_seconds=settings.arxiv_min_request_interval_seconds,
    )
    repository = QdrantRepository(
        url=settings.qdrant_url, collection_name=settings.qdrant_collection_name
    )

    # Initialize counters for the ingestion summary
    papers_processed: int = 0
    chunks_upserted: int = 0
    collection_ready: bool = False

    # Iterate over pages of arXiv papers and process them
    try:
        async for page in iter_arxiv_papers(
            arxiv_client,
            search_query=search_query,
            max_results_per_page=settings.arxiv_max_results_per_page,
            max_total_results=max_total_results,
        ):
            # Chunk each paper into smaller pieces for embedding
            chunks: list[PaperChunk] = [
                chunk
                for paper in page
                for chunk in chunk_paper(
                    paper,
                    max_characters=settings.chunk_max_characters,
                    overlap_characters=settings.chunk_overlap_characters,
                )
            ]
            # Update the count of processed papers and check if there are any chunks to embed
            papers_processed += len(page)
            if not chunks:
                continue
            # Embed the text of each chunk and prepare them for upsert into Qdrant
            vectors = await embed_texts(
                [chunk.text for chunk in chunks], model_name=settings.embedding_model_name
            )
            # Ensure the Qdrant collection exists before upserting points
            if not collection_ready:
                await repository.ensure_collection(vector_size=len(vectors[0]))
                collection_ready = True
            # Prepare Qdrant points with deterministic IDs and payloads for upsert
            points = [
                QdrantPoint(
                    point_id=_chunk_point_id(chunk),
                    vector=vector,
                    payload=_chunk_payload(chunk),
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            # Upsert the points into the Qdrant collection and update the count of upserted chunks
            await repository.upsert_points(points)
            chunks_upserted += len(points)
    finally:
        arxiv_client.close()
        await repository.close()

    return IngestionSummary(papers_processed=papers_processed, chunks_upserted=chunks_upserted)


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
