"""Environment-driven runtime configuration shared across modules."""

from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
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

    # Redis settings
    redis_url: str = "redis://localhost:6379/0"

    # Retrieval settings
    retrieval_top_k: int = 5
    retrieval_score_threshold: float = 0.2
    retrieval_cache_ttl_seconds: int = 3600

    # Frontend settings
    backend_api_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("BACKEND_API_BASE_URL", "backend_api_base_url"),
    )

    # Embedding settings
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"

    # LLM settings
    llm_api_base: str = Field(
        default="http://localhost:4000",
        validation_alias=AliasChoices("LITELLM_API_BASE", "LLM_API_BASE", "llm_api_base"),
    )
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LITELLM_API_KEY", "LLM_API_KEY", "llm_api_key"),
    )
    llm_model_name: str = Field(
        default="openrouter/google/gemma-4-26b-a4b-it:free",
        validation_alias=AliasChoices("LITELLM_MODEL_NAME", "LLM_MODEL_NAME", "llm_model_name"),
    )
    llm_temperature: float = Field(
        default=0.2,
        validation_alias=AliasChoices("LITELLM_TEMPERATURE", "LLM_TEMPERATURE", "llm_temperature"),
    )
    llm_max_tokens: int = Field(
        default=512,
        validation_alias=AliasChoices("LITELLM_MAX_TOKENS", "LLM_MAX_TOKENS", "llm_max_tokens"),
    )
    llm_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "LITELLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS", "llm_timeout_seconds"
        ),
    )
    llm_max_retries: int = Field(
        default=2,
        validation_alias=AliasChoices("LITELLM_MAX_RETRIES", "LLM_MAX_RETRIES", "llm_max_retries"),
    )
    llm_retry_backoff_seconds: float = Field(
        default=0.5,
        validation_alias=AliasChoices(
            "LITELLM_RETRY_BACKOFF_SECONDS",
            "LLM_RETRY_BACKOFF_SECONDS",
            "llm_retry_backoff_seconds",
        ),
    )

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
