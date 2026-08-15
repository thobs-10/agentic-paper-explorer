"""Tests for arXiv paper chunking."""

from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import ArxivPaperRecord
from agentic_paper_explorer.ingestion.processing.chunking import chunk_paper


def _make_paper(*, title: str, summary: str) -> ArxivPaperRecord:
    return ArxivPaperRecord(
        paper_id="paper-1",
        title=title,
        summary=summary,
        published="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        authors=["Author One"],
        categories=["cs.AI"],
        primary_category="cs.AI",
        comment=None,
        journal_reference=None,
        pdf_url="https://arxiv.org/pdf/paper-1",
        entry_url="https://arxiv.org/abs/paper-1",
    )


def test_chunk_paper_returns_single_chunk_for_short_abstract() -> None:
    paper = _make_paper(title="A short title", summary="A short abstract.")

    chunks = chunk_paper(paper, max_characters=1800, overlap_characters=200)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.paper_id == "paper-1"
    assert chunk.chunk_index == 0
    assert chunk.text == "A short title\n\nA short abstract."
    assert chunk.title == "A short title"
    assert chunk.authors == ["Author One"]
    assert chunk.categories == ["cs.AI"]
    assert chunk.published == "2026-01-01T00:00:00Z"
    assert chunk.pdf_url == "https://arxiv.org/pdf/paper-1"
    assert chunk.entry_url == "https://arxiv.org/abs/paper-1"


def test_chunk_paper_splits_long_abstract_with_overlap() -> None:
    paper = _make_paper(title="Title", summary="x" * 50)

    chunks = chunk_paper(paper, max_characters=20, overlap_characters=5)

    assert len(chunks) > 1
    assert all(chunk.chunk_index == index for index, chunk in enumerate(chunks))
    combined_text = f"Title\n\n{'x' * 50}"
    assert len(chunks[0].text) == 20
    # consecutive chunks overlap by the configured amount
    assert chunks[0].text[-5:] == chunks[1].text[:5]
    assert chunks[-1].text == combined_text[-len(chunks[-1].text) :]


def test_chunk_paper_returns_empty_list_for_blank_title_and_summary() -> None:
    paper = _make_paper(title="", summary="")

    chunks = chunk_paper(paper, max_characters=1800, overlap_characters=200)

    assert chunks == []
