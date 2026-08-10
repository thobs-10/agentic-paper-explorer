"""Pydantic models for the arXiv ingestion API."""

from pydantic import BaseModel, Field


class ArxivSearchRequest(BaseModel):
    """Query parameters for an arXiv paper search."""

    search_query: str = Field(
        min_length=1, description="arXiv search query, for example all:transformer"
    )
    start: int = Field(
        default=0, ge=0, description="Zero-based index for the first result to fetch"
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of papers to fetch from arXiv for this request",
    )


class ArxivPaperResponse(BaseModel):
    """Normalized paper payload returned by the ingestion API."""

    paper_id: str
    title: str
    summary: str
    published: str
    updated: str
    authors: list[str]
    categories: list[str]
    primary_category: str | None = None
    comment: str | None = None
    journal_reference: str | None = None
    pdf_url: str | None = None
    entry_url: str | None = None


class ArxivSearchResponse(BaseModel):
    """Top-level arXiv search response for the REST API."""

    total_results: int
    start_index: int
    items_per_page: int
    papers: list[ArxivPaperResponse]
