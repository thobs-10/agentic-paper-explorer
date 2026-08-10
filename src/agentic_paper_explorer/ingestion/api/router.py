"""API router for arXiv ingestion queries."""

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from agentic_paper_explorer.ingestion.api.models import (
    ArxivPaperResponse,
    ArxivSearchRequest,
    ArxivSearchResponse,
)
from agentic_paper_explorer.ingestion.data_ingestion.arxiv_client import ArxivClient

DEFAULT_ALLOWED_ORIGINS = ["*"]


app = FastAPI(
    title="arXiv paper ingestion API",
    description="API for ingesting arXiv papers into the agentic paper explorer system",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEFAULT_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create router
api_router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


def get_arxiv_client() -> ArxivClient:
    """Create the arXiv client dependency for route handlers."""

    return ArxivClient()


def build_search_request(
    search_query: str = Query(
        ..., min_length=1, description="arXiv search query, for example all:llm"
    ),
    start: int = Query(0, ge=0, description="Zero-based starting index"),
    max_results: int = Query(10, ge=1, le=100, description="Number of records to fetch"),
) -> ArxivSearchRequest:
    """Normalize query parameters into a typed request model."""

    return ArxivSearchRequest(search_query=search_query, start=start, max_results=max_results)


@api_router.get("/papers/search", response_model=ArxivSearchResponse)
async def search_arxiv_papers(
    request: ArxivSearchRequest = Depends(build_search_request),
    arxiv_client: ArxivClient = Depends(get_arxiv_client),
) -> ArxivSearchResponse:
    """Fetch a bounded page of papers from the arXiv REST API.
    args:
        request: The search request parameters.
        arxiv_client: The arXiv client dependency.
    returns:
        An `ArxivSearchResponse` containing the normalized paper records.
    """

    try:
        result = await arxiv_client.search_papers(
            search_query=request.search_query,
            start=request.start,
            max_results=request.max_results,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to fetch data from arXiv") from exc

    return ArxivSearchResponse(
        total_results=result.total_results,
        start_index=result.start_index,
        items_per_page=result.items_per_page,
        papers=[
            ArxivPaperResponse.model_validate(paper, from_attributes=True)
            for paper in result.papers
        ],
    )


app.include_router(api_router)
