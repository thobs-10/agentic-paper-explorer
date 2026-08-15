"""Environment-driven runtime configuration shared across modules."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ALLOWED_ORIGINS = ["http://localhost:8501"]


class Settings(BaseSettings):
    """Central runtime configuration loaded from environment variables or `.env`."""

    # reading the .env file is optional; if it doesn't exist, the environment variables will be used instead
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # CORS settings
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_ORIGINS)
    )
    # arxiv API settings
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    arxiv_timeout_seconds: float = 15.0
    arxiv_max_retries: int = 3
    arxiv_retry_backoff_seconds: float = 1.0
    arxiv_min_request_interval_seconds: float = 3.0
    arxiv_max_results_per_page: int = 50

    # Qdrant settings
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_name: str = "arxiv_papers"

    # Embedding settings
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"

    # Chunking settings
    chunk_max_characters: int = 1800
    chunk_overlap_characters: int = 200

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_csv_origins(cls, value: object) -> object:
        """Allow ALLOWED_ORIGINS to be provided as a comma-separated string."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached `Settings` instance."""
    return Settings()
