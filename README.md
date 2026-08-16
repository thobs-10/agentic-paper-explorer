# agentic-paper-explorer
Agentic RAG application that interacts with arXiv to fetch papers based on the user's interest and displays them.

## Local infrastructure

Phase 0 infrastructure is defined in [docker-compose.yml](/Users/thobelasixpence/Documents/portfolio-projects/agentic-paper-explorer/docker-compose.yml).

Services:
- Qdrant HTTP on `localhost:6333`
- Qdrant gRPC on `localhost:6334`
- Redis on `localhost:6379`

Start the local services with:

```bash
docker compose up -d
```

Default local connection settings are listed in [.env.example](/Users/thobelasixpence/Documents/portfolio-projects/agentic-paper-explorer/.env.example).

Convenience targets are in [Makefile](/Users/thobelasixpence/Documents/portfolio-projects/agentic-paper-explorer/Makefile):

```bash
make infra-config   # validate the compose file
make infra-up       # start qdrant and redis
make infra-ps       # show service status
make infra-logs     # tail service logs
make infra-down     # stop and remove services
```

Both services declare health checks, so `docker compose ps` reports readiness rather than just container liveness. Data is persisted in the `qdrant_data` and `redis_data` named volumes.

## Phase 0 - DB configuration and arXiv ingestion API

Phase 0 delivers the local datastores plus a typed, batched read path over the public arXiv Atom API. No data is written to Qdrant yet; that begins in Phase 1.

### What was built

| Concern | Location |
| --- | --- |
| arXiv HTTP client and Atom parsing | [arxiv_client.py](src/agentic_paper_explorer/ingestion/data_ingestion/arxiv_client.py) |
| Request and response contracts | [models.py](src/agentic_paper_explorer/ingestion/api/models.py) |
| FastAPI app and route | [router.py](src/agentic_paper_explorer/ingestion/api/router.py) |
| Tests mirroring the source tree | [tests/ingestion](tests/ingestion) |

### arXiv client

`ArxivClient` wraps `https://export.arxiv.org/api/query` and returns normalized records instead of raw XML.

- `search_papers(search_query, start, max_results)` is the async entry point. The underlying `httpx` call is synchronous and is offloaded with `asyncio.to_thread`, so the FastAPI event loop is never blocked.
- Responses are parsed with `defusedxml` rather than the stdlib XML parser, to avoid entity-expansion and external-entity attacks on untrusted feed content.
- Parsing returns two frozen, slotted dataclasses:
  - `ArxivPaperRecord` - one paper (id, title, summary, published/updated timestamps, authors, categories, primary category, comment, journal reference, PDF link, entry link).
  - `ArxivSearchResult` - the page envelope (`total_results`, `start_index`, `items_per_page`, `papers`).
- Text fields are whitespace-normalized, and optional fields collapse to `None` when blank, so downstream chunking and embedding do not have to re-clean the data.
- Parsing is exposed as a pure static method (`parse_search_response`), which keeps it testable without network access.

### Batched fetching model

arXiv paginates through an offset window rather than a cursor, so batching is expressed as `start` plus `max_results`:

- `start` - zero-based offset of the first record in the batch (`ge=0`).
- `max_results` - batch size, bounded to `1..100` to stay within arXiv's practical page limit and to cap memory and latency per request.
- `total_results` in the response tells the caller how many batches remain, so a pipeline can walk pages by advancing `start` by `max_results` until `start >= total_results`.

Bounds are enforced twice on purpose: at the FastAPI query layer (fast rejection with HTTP 422) and in the Pydantic model (protects any non-HTTP caller of the same contract).

### REST endpoint

```
GET /api/v1/ingestion/papers/search?search_query=all:llm&start=0&max_results=10
```

- Query parameters are normalized into `ArxivSearchRequest` through a `Depends` factory, keeping the handler free of parameter parsing.
- `ArxivClient` is injected through `get_arxiv_client`, so tests can override the dependency instead of patching module globals.
- The handler stays thin: call the client, map the dataclasses onto `ArxivPaperResponse` via `model_validate(..., from_attributes=True)`, return `ArxivSearchResponse`.
- Upstream failures (timeouts, non-2xx from arXiv, malformed feeds) are translated into HTTP 502 with a generic message, so upstream internals are not leaked to clients.

Run the API locally:

```bash
uv run uvicorn agentic_paper_explorer.ingestion.api.router:app --reload
```

Interactive docs are then available at `http://localhost:8000/docs`.

Example request:

```bash
curl "http://localhost:8000/api/v1/ingestion/papers/search?search_query=all:retrieval%20augmented%20generation&start=0&max_results=5"
```

### Verification

```bash
uv run pytest tests/ingestion
uv run ruff check .
uv run bandit -r src
```

Tests cover Atom parsing, offload to `asyncio.to_thread`, request URL construction, the bounded success path, and the 502 upstream-failure path. All external HTTP calls are mocked, so the suite is deterministic and offline.

### Phase 0 hardening

Before Phase 1 ingestion pipelines were built, the following gaps were closed:

- CORS origins are now read from `ALLOWED_ORIGINS` via [settings.py](src/agentic_paper_explorer/configs/settings.py) instead of a hardcoded wildcard.
- `ArxivClient` reuses one pooled `httpx.Client` for its lifetime (created once via a FastAPI `lifespan` hook in [router.py](src/agentic_paper_explorer/ingestion/api/router.py)) instead of opening a new client per request.
- Requests to arXiv are rate-limited (`ARXIV_MIN_REQUEST_INTERVAL_SECONDS`, default 3s) and retried with exponential backoff on transient 5xx/timeout responses (`ARXIV_MAX_RETRIES`, `ARXIV_RETRY_BACKOFF_SECONDS`).

## Phase 1 - Pipeline ingestion to Qdrant

Phase 1 adds the end-to-end ingestion pipeline that turns an arXiv search prompt into chunked, embedded vectors stored in Qdrant.

### What was built

| Concern | Location |
| --- | --- |
| Standalone pipeline runner | [src/agentic_paper_explorer/ingestion/pipeline.py](src/agentic_paper_explorer/ingestion/pipeline.py) |
| Batch pagination over arXiv pages | [src/agentic_paper_explorer/ingestion/data_ingestion/batch_reader.py](src/agentic_paper_explorer/ingestion/data_ingestion/batch_reader.py) |
| Chunking into embeddable text windows | [src/agentic_paper_explorer/ingestion/processing/chunking.py](src/agentic_paper_explorer/ingestion/processing/chunking.py) |
| Embedding model wrapper | [src/agentic_paper_explorer/ingestion/processing/embeddings.py](src/agentic_paper_explorer/ingestion/processing/embeddings.py) |
| Qdrant write abstraction | [src/agentic_paper_explorer/backend/database/qdrant_client.py](src/agentic_paper_explorer/backend/database/qdrant_client.py) |
| UI/API trigger contract | [src/agentic_paper_explorer/ingestion/api/models.py](src/agentic_paper_explorer/ingestion/api/models.py) and [src/agentic_paper_explorer/ingestion/api/router.py](src/agentic_paper_explorer/ingestion/api/router.py) |
| Regression tests | [tests/ingestion](tests/ingestion) and [tests/backend/database](tests/backend/database) |

### Pipeline behavior

The pipeline does the following for a search query such as `all:transformer`:

1. fetches arXiv pages in batches with a bounded page-size
2. chunks each paper title + summary into windows with overlap
3. embeds each chunk through the configured Hugging Face embedding model
4. ensures the target Qdrant collection exists
5. upserts deterministic point IDs and payload metadata into Qdrant
6. returns a summary showing how many papers and chunks were processed

The production trigger is the FastAPI route that accepts the UI prompt and calls the same pipeline function. The CLI is a helper for local smoke tests and debugging.

### Standalone CLI validation

```bash
uv run python -m agentic_paper_explorer.ingestion.pipeline "all:transformer"
```

The CLI is intentionally bounded to a safe default (`--max-results 10`) so a manual run does not accidentally crawl large arXiv result sets.

### API trigger

```bash
curl -X POST "http://localhost:8000/api/v1/ingestion/papers/process" \
  -H "Content-Type: application/json" \
  -d '{"search_query":"all:transformer","max_results":10}'
```

This is the real UI-to-backend trigger path: the prompt is sent to the API, which calls `run_ingestion_pipeline(...)` and returns a summary response.

### Verification

```bash
uv run pytest tests/backend/database/test_qdrant_client.py tests/ingestion/api/test_router.py tests/ingestion/test_pipeline.py -q
uv run ruff check .
uv run uvicorn agentic_paper_explorer.ingestion.api.router:app --reload
```

### Notable hardening added in Phase 1

- arXiv 429 rate-limit responses are retried instead of failing immediately
- the pipeline uses deterministic point IDs so repeated ingests are idempotent
- the pipeline CLI has a safe default cap for manual runs
- the Qdrant repository is isolated behind a thin repository wrapper for collection ensures and upserts

### Known follow-ups

- continue to the next phase with retrieval and agentic prompt processing
- add a proper status/queue model if ingestion becomes asynchronous
- pin Qdrant client/server versions to avoid compatibility warnings in the live container

## Phase 2 - Retrieval and cached context assembly

Phase 2 introduces the retrieval layer used to turn a user prompt into ranked paper chunks before generation. The current implementation is intentionally a pragmatic baseline: fast Redis lookup first, then semantic search in Qdrant, then context packaging for the next agent/generation stage.

### What was built

| Concern | Location |
| --- | --- |
| Retrieval orchestration service | [src/agentic_paper_explorer/backend/retrieval/service.py](src/agentic_paper_explorer/backend/retrieval/service.py) |
| Qdrant similarity search contract | [src/agentic_paper_explorer/backend/database/qdrant_client.py](src/agentic_paper_explorer/backend/database/qdrant_client.py) |
| Retrieval regression tests | [tests/backend/retrieval/test_retrieval_service.py](tests/backend/retrieval/test_retrieval_service.py) |

### Retrieval behavior

The retrieval service currently follows this flow:

1. normalize the prompt into a cache key
2. look up cached results in Redis
3. on a miss, embed the query with the configured embedding function
4. search the Qdrant collection for top-k semantic matches
5. filter matches by the configured score threshold
6. map payloads into `RetrievedChunk` objects with paper metadata and source URLs
7. store the final ranked context back in Redis with a TTL for repeated queries

This gives us a strong latency win for repeated prompts while still supporting semantic search when no cached result exists.

### Current design choices

The phase is deliberately scoped to a cache-first + semantic retrieval pattern rather than a full hybrid retrieval stack:

- Redis is used as a prompt-result cache to reduce repeated vector-search cost.
- Qdrant remains the semantic retrieval backend for similarity search over embedded chunk vectors.
- ranking is handled by the score returned from Qdrant, with lightweight filtering before packaging.
- the cached payload preserves the prompt and the chunk list in a compact, generation-ready shape.

This is a sound milestone for the project, but it is not yet a full hybrid retrieval system with lexical matching, multi-source merging, or reranking across multiple retrieval strategies.

### Deferred enhancements

These remain intentionally out of scope for this commit and can be added in a later pass:

- lexical search or BM25-style retrieval for exact-term recall
- hybrid result merging across semantic and lexical signals
- reranking of combined results before final context assembly
- richer Redis metadata, including versioning and invalidation keys
- generation-facing API contract for sending packaged context to the LLM layer

### Verification

```bash
uv run pytest tests/backend/retrieval/test_retrieval_service.py -q
uv run ruff check src/agentic_paper_explorer/backend/retrieval/service.py src/agentic_paper_explorer/backend/database/qdrant_client.py
```

This keeps the retrieval phase testable and isolated while leaving room for the response-generation layer to build on top of the resulting context bundle.

## Phase 3 - Reliable response generation

Phase 3 adds grounded response generation through the LiteLLM gateway. The application uses the configured lightweight open-source model and keeps provider-specific calls behind [provider.py](src/agentic_paper_explorer/backend/generation/provider.py).

### Generation failure behavior

- Each provider call has a bounded timeout controlled by `LITELLM_TIMEOUT_SECONDS` (default 30 seconds).
- Rate limits (`429`), upstream server failures (`5xx`), timeouts, and network failures are retried with exponential backoff. The defaults are two retries and a 0.5 second initial delay.
- Non-transient provider errors, such as invalid requests, are not retried.
- Provider exceptions are mapped to stable categories (`rate_limit`, `upstream`, `timeout`, `network`, or `provider`) and detailed provider messages are kept out of the API response.
- When all attempts fail, the generation service returns a concise fallback message and preserves the retrieved paper source links so the client still has traceable context.
- Provider attempts and failure categories are emitted through the module logger for operational tracing.

The policy is configured with:

```text
LITELLM_TIMEOUT_SECONDS=30.0
LITELLM_MAX_RETRIES=2
LITELLM_RETRY_BACKOFF_SECONDS=0.5
```

### Verification

```bash
uv run pytest tests/backend/generation tests/configs/test_settings.py -q
uv run ruff check src/agentic_paper_explorer/backend/generation src/agentic_paper_explorer/configs/settings.py tests/backend/generation tests/configs/test_settings.py
```
