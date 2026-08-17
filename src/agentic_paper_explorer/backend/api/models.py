"""Request and response contracts for the generation API."""

from pydantic import BaseModel, Field


class GenerationRequest(BaseModel):
    """Request payload for asking a question against retrieved paper context."""

    query: str = Field(
        min_length=1, description="Question to answer from the retrieved paper context"
    )


class GenerationResponse(BaseModel):
    """Response payload returned after context-grounded generation."""

    query: str
    answer: str
    sources: list[str] = Field(default_factory=list)
    model: str | None = None
    degraded: bool = Field(
        default=False, description="True when the answer text is a fallback, not model output"
    )
    error_category: str | None = Field(
        default=None, description="Normalized provider failure category when degraded"
    )
