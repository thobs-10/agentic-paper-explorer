"""Chunking of arXiv paper metadata into embeddable text units."""

from __future__ import annotations

from dataclasses import dataclass

from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import ArxivPaperRecord


@dataclass(slots=True, frozen=True)
class PaperChunk:
    """A single embeddable unit of a paper's title and abstract, with its metadata."""

    paper_id: str
    chunk_index: int
    text: str
    title: str
    authors: list[str]
    categories: list[str]
    published: str
    pdf_url: str | None
    entry_url: str | None


def chunk_paper(
    paper: ArxivPaperRecord,
    *,
    max_characters: int,
    overlap_characters: int,
) -> list[PaperChunk]:
    """Split a paper's title and abstract into one or more embeddable chunks.

    Most abstracts fit within `max_characters` and yield a single chunk; longer
    text falls back to overlapping windows so no content is silently dropped.

    Args:
        paper: The `ArxivPaperRecord` to chunk.
        max_characters: The maximum number of characters per chunk.
        overlap_characters: The number of characters to overlap between consecutive chunks.
    Returns:
        A list of `PaperChunk` objects, one per chunk of the paper's title and abstract.
    """
    combined_text = f"{paper.title}\n\n{paper.summary}".strip()
    if not combined_text:
        return []

    text_parts = _split_text(combined_text, max_characters, overlap_characters)
    return [
        PaperChunk(
            paper_id=paper.paper_id,
            chunk_index=index,
            text=part,
            title=paper.title,
            authors=paper.authors,
            categories=paper.categories,
            published=paper.published,
            pdf_url=paper.pdf_url,
            entry_url=paper.entry_url,
        )
        for index, part in enumerate(text_parts)
    ]


def _split_text(
    text: str,
    max_characters: int,
    overlap_characters: int,
) -> list[str]:
    """Greedily split text into overlapping windows bounded by `max_characters`.
    aggregate the title and abstract into a single string, then split it into chunks
    of at most `max_characters` characters, with an overlap of `overlap_characters`
    between consecutive chunks.

    Args:
        text: The text to split.
        max_characters: The maximum number of characters per chunk.
        overlap_characters: The number of characters to overlap between consecutive chunks.
    Returns:
        A list of text chunks, each of at most `max_characters` characters."""
    if len(text) <= max_characters:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_characters, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap_characters
    return chunks
