# Phase 1 - Ingestion pipeline to Qdrant

Phase 1 adds the end-to-end ingestion pipeline that turns an arXiv search prompt into chunked,
embedded vectors stored in Qdrant.

## What was built

| Concern | Location |
| --- | --- |
| Standalone pipeline runner | [pipeline.py](../../src/agentic_paper_explorer/ingestion/pipeline.py) |
| Batch pagination over arXiv pages | [batch_reader.py](../../src/agentic_paper_explorer/ingestion/data_ingestion/batch_reader.py) |
| Chunking into embeddable text windows | [chunking.py](../../src/agentic_paper_explorer/ingestion/processing/chunking.py) |
| Embedding model wrapper | [embeddings.py](../../src/agentic_paper_explorer/ingestion/processing/embeddings.py) |
| Qdrant write abstraction | [qdrant_client.py](../../src/agentic_paper_explorer/backend/database/qdrant_client.py) |
| UI/API trigger contract | [models.py](../../src/agentic_paper_explorer/ingestion/api/models.py), [router.py](../../src/agentic_paper_explorer/ingestion/api/router.py) |
| Regression tests | [tests/ingestion](../../tests/ingestion), [tests/backend/database](../../tests/backend/database) |

## Pipeline behavior

The pipeline does the following for a search query such as `all:transformer`:

1. fetches arXiv pages in batches with a bounded page-size
2. chunks each paper title + summary into windows with overlap
3. embeds each chunk through the configured Hugging Face embedding model
4. ensures the target Qdrant collection exists
5. upserts deterministic point IDs and payload metadata into Qdrant
6. returns a summary showing how many papers and chunks were processed

The production trigger is the FastAPI route that accepts the UI prompt and calls the same pipeline
function. The CLI is a helper for local smoke tests and debugging.

## Standalone CLI validation

```bash
uv run python -m agentic_paper_explorer.ingestion.pipeline "all:transformer"
```

The CLI is intentionally bounded to a safe default (`--max-results 10`) so a manual run does not
accidentally crawl large arXiv result sets.

## API trigger

```bash
curl -X POST "http://localhost:8000/api/v1/ingestion/papers/process" \
  -H "Content-Type: application/json" \
  -d '{"search_query":"all:transformer","max_results":10}'
```

This is the real UI-to-backend trigger path: the prompt is sent to the API, which calls
`run_ingestion_pipeline(...)` and returns a summary response.

## Verification

```bash
uv run pytest tests/backend/database/test_qdrant_client.py tests/ingestion/api/test_router.py tests/ingestion/test_pipeline.py -q
uv run ruff check .
uv run uvicorn agentic_paper_explorer.ingestion.api.router:app --reload
```

## Notable hardening

- arXiv 429 rate-limit responses are retried instead of failing immediately
- the pipeline uses deterministic point IDs so repeated ingests are idempotent
- the pipeline CLI has a safe default cap for manual runs
- the Qdrant repository is isolated behind a thin repository wrapper for collection ensures and
  upserts

## Known follow-ups

- add a proper status/queue model if ingestion becomes asynchronous
- pin Qdrant client/server versions to avoid compatibility warnings in the live container
