# agentic-paper-explorer
Agentic RAG application that interacts with arXiv to fetch papers based on the user's interest and displays them.

## Local infrastructure

The full stack is defined in [docker-compose.yml](docker-compose.yml) and built from the multi-stage [Dockerfile](Dockerfile).

| Service | Port | Role |
| --- | --- | --- |
| `frontend` | 8501 | Streamlit UI |
| `backend` | 8000 | Retrieval + generation API |
| `ingestion` | 8001 | arXiv ingestion API |
| `litellm` | 4000 | Model gateway |
| `litellm-db` | internal | LiteLLM metadata store |
| `qdrant` | 6333 / 6334 | Vector database (HTTP / gRPC) |
| `redis` | 6379 | Retrieval cache |

Start everything with:

```bash
cp .env.example .env   # then set OPENROUTER_API_KEY
docker compose up -d
```

Default local connection settings are listed in [.env.example](.env.example).

Convenience targets are in [Makefile](Makefile):

```bash
make infra-config   # validate the compose file
make infra-up       # start qdrant, redis, litellm only
make build          # build backend, ingestion, frontend images
make up             # start the whole stack
make ps             # show service status
make logs           # tail application logs
make down           # stop and remove services
```

Every service declares a health check, so `docker compose ps` reports readiness rather than just container liveness. Dependencies use `condition: service_healthy`, so the backend does not start before Qdrant, Redis, and the model gateway are actually accepting connections. Data persists in the `qdrant_data`, `redis_data`, `litellm_pg_data`, and `hf_cache` named volumes; `hf_cache` is shared between the backend and ingestion containers so the embedding model is downloaded once.

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
- Provider exceptions are mapped to stable categories (`rate_limit`, `upstream`, `timeout`, `network`, `empty_response`, or `provider`) and detailed provider messages are kept out of the API response.
- When all attempts fail, the generation service returns a concise fallback message and preserves the retrieved paper source links so the client still has traceable context. Since Phase 5 the response is also flagged `degraded` and returned with HTTP 502.
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

## Phase 3 - Grounded prompting and citations

The generation layer uses a citation-aware prompt contract so responses remain traceable to retrieved paper excerpts.

### Answer contract

- Context chunks are ordered by descending retrieval score before they are sent to the provider.
- Each chunk receives a stable marker such as `[1]` and includes its title, source URL or paper ID, and excerpt text.
- Every material claim should cite the supporting marker immediately, for example: `The method improves recall [1].`
- The provider must use only the supplied excerpts and must not invent claims, citations, URLs, or marker numbers.
- The answer should begin with a concise direct response, followed by brief evidence or limitations when useful.
- The API returns unique source URLs separately in the `sources` field; the model is instructed not to add a separate references section.

### Insufficient context

When retrieval returns no usable text, generation abstains before calling the provider and returns:

```text
I do not have enough retrieved paper context to answer this question reliably.
```

The response still includes any available source URLs. This prevents an LLM from guessing when retrieval did not provide enough evidence.

### Verification

```bash
uv run pytest tests/backend/generation/test_generation_service.py -q
```

## Phase 3 - Streaming generation

The streaming endpoint exposes the same grounded generation flow over Server-Sent Events (SSE). The existing JSON endpoint remains available when a client needs one complete response.

### Endpoint

```text
POST /api/v1/generation/answer/stream
Content-Type: application/json
Accept: text/event-stream
```

Request body:

```json
{"query":"How does retrieval improve generation?"}
```

The stream emits three event types:

```text
event: start
data: {"query":"How does retrieval improve generation?"}

event: chunk
data: {"text":"Retrieval provides "}

event: complete
data: {"sources":["https://arxiv.org/abs/example"],"model":"..."}
```

- `start` identifies the query.
- `chunk` contains a partial text delta and may occur many times. Clients should append `text` values in order.
- `complete` is the terminal event and contains the unique source URLs and model name, plus `degraded` and `error_category` since Phase 5.
- If retrieval has no usable context, the stream emits the deterministic abstention message as one `chunk`, followed by `complete`, without calling the provider.
- If the provider fails after retries, the stream emits an `error` event carrying the failure category and still terminates with `complete`. Clients can continue displaying already received partial output.

For clients that do not support SSE, use `POST /api/v1/generation/answer`, which returns the complete `GenerationResponse` JSON contract.

### Verification

```bash
uv run pytest tests/backend/generation tests/backend/api/test_generation_router.py -q
```

## Phase 4 - Streamlit UI

The Streamlit frontend lives under [frontend](src/agentic_paper_explorer/frontend) and uses the generation API through a small testable HTTP client.

Start the backend and UI in separate terminals:

```bash
uv run uvicorn agentic_paper_explorer.backend.api.router:app --reload
uv run streamlit run src/agentic_paper_explorer/frontend/app.py
```

The UI opens at `http://localhost:8501`. Configure another backend with:

```text
BACKEND_API_BASE_URL=http://localhost:8000
```

The UI streams answer chunks by default, displays the final sources and model metadata, warns when a stream ends after partial output, and falls back to the complete JSON endpoint when streaming cannot start. Insufficient retrieval context is shown as a normal abstention state rather than a transport error.

## Phase 5 - Containerization and end-to-end validation

Phase 5 packages every component as a container, runs the first real end-to-end query through the whole system, and closes the failure-visibility gaps that end-to-end testing exposed.

### What was built

| Concern | Location |
| --- | --- |
| Multi-stage build for all services | [Dockerfile](Dockerfile) |
| Service topology, health checks, volumes | [docker-compose.yml](docker-compose.yml) |
| Build context exclusions | [.dockerignore](.dockerignore) |
| Container and local run targets | [Makefile](Makefile) |
| Liveness endpoints | [backend router](src/agentic_paper_explorer/backend/api/router.py), [ingestion router](src/agentic_paper_explorer/ingestion/api/router.py) |
| Degraded-response contract | [models.py](src/agentic_paper_explorer/backend/api/models.py), [service.py](src/agentic_paper_explorer/backend/generation/service.py) |
| Empty-response guard | [provider.py](src/agentic_paper_explorer/backend/generation/provider.py) |

### Image layout

The Dockerfile uses one shared runtime base and three service targets (`backend`, `ingestion`, `frontend`). Dependency layers are resolved per service with `uv sync --extra <service>`, so the frontend image does not carry the embedding or vector-store stack. Only lock metadata is copied before dependency resolution, which keeps dependency layers cached when application source changes. All services run as a non-root `app` user, and the Hugging Face cache directory is created and owned in the image so the named volume mount does not end up root-owned.

Application source is baked in with `COPY src ./src` and is not bind-mounted, which has an operational consequence worth knowing:

| Change | Action required |
| --- | --- |
| Provider API key | recreate `litellm` only |
| Model slug or other env var | recreate `litellm` and `backend` |
| Python source | **rebuild** the affected image (`docker compose up -d --build backend`) |

### Request flow

An end-to-end request moves through the system as follows. Ingestion is a separate service and is not triggered by a query; the backend answers from whatever is already stored in Qdrant.

```text
Streamlit UI
  -> POST /api/v1/generation/answer
     -> Redis lookup (key: prompt:<normalized-slug>)
        -> on miss: embed query -> Qdrant top-k search -> cache the ranked chunks
     -> GenerationService builds the citation-aware prompt
        -> LiteLLM gateway -> model provider
  <- answer + sources + model + degraded flag
```

### Failure visibility

End-to-end testing showed that a misconfigured model gateway returned `HTTP 200` with a friendly fallback sentence, which made an operator-level outage look like a normal answer. Generation failures are now explicit:

- `GenerationResult` and `GenerationResponse` carry `degraded: bool` and `error_category: str | None`.
- The JSON endpoint returns **HTTP 502** when generation is degraded, while still returning the retrieved `sources` so the client can show traceable context.
- The streaming endpoint emits a dedicated `error` event with the failure category, then terminates with `complete` carrying `degraded` and `error_category`.
- Retrieval abstention is *not* treated as degraded. Missing evidence is a valid answer; a broken provider is not.

Example degraded response:

```json
{
  "query": "What are transformer models used for in NLP?",
  "answer": "I could not generate an answer right now. Please try again shortly. ...",
  "sources": ["https://arxiv.org/abs/2311.17633v2", "..."],
  "model": "litellm_proxy/openrouter/google/gemma-4-26b-a4b-it:free",
  "degraded": true,
  "error_category": "upstream"
}
```

### Empty model responses

Reasoning-oriented models return their text in a separate `reasoning` field and leave `message.content` empty. Reading only `content` would have produced blank answers with `HTTP 200`, which is the same class of silent failure as above. The provider now raises `ProviderError(category="empty_response", retryable=False)` when a completion or a stream yields no usable content, so it flows into the degraded path. `_classify_provider_error` also passes existing `ProviderError` instances through unchanged, so the category is not lost when the error is raised inside the retry block.

The default model is `openrouter/google/gemma-4-26b-a4b-it:free`, which returns standard message content. When changing models, verify the candidate populates `message.content` rather than only `reasoning`.

### Verification

```bash
docker compose up -d
docker compose ps                      # every service should report (healthy)

# non-streaming
curl -s -X POST http://localhost:8000/api/v1/generation/answer \
  -H 'Content-Type: application/json' \
  -d '{"query":"What are transformer models used for in NLP?"}' | python3 -m json.tool

# streaming
curl -s -N -X POST http://localhost:8000/api/v1/generation/answer/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is attention in neural networks?"}'

# degraded path
docker compose stop litellm && curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost:8000/api/v1/generation/answer \
  -H 'Content-Type: application/json' -d '{"query":"anything"}'   # expect 502
docker compose start litellm
```

Observed on a corpus of 4192 chunks: cold request `HTTP 200` in ~20s returning a cited answer with 5 sources, streaming delivering token-level deltas, and `HTTP 502` with `error_category: "upstream"` when the gateway is stopped.

Full suite:

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run ruff format --check src tests
```

### Operational notes

- **Redis caches retrieval, not answers.** A repeated query still calls the model; only the embedding and vector search are skipped. Answer caching is a separate decision.
- **The corpus must be populated first.** A query against an empty collection returns the abstention message, not an error. Load data with `POST /api/v1/ingestion/papers/process` on port 8001.
- **Integration tests create and drop their own Qdrant collections.** Interrupted runs can leave `integration-test-*` collections behind; delete them directly if they accumulate.

### Known follow-ups

- no metrics, traces, or dashboards yet, so latency and failure categories are only visible in container logs
- `degraded` and `error_category` are returned to clients but not yet exported as monitoring signals
- Qdrant client and server versions differ enough to emit a compatibility warning and should be pinned
- answer-level caching and a hybrid retrieval pass remain open from earlier phases

## Next phase - Monitoring and observability

The system is now fully containerized and verified end to end, which makes it a sound base for instrumentation. The next phase adds OpenTelemetry instrumentation and Grafana dashboards under [monitoring](src/agentic_paper_explorer/monitoring), with the failure categories introduced in Phase 5 (`rate_limit`, `upstream`, `timeout`, `network`, `empty_response`, `provider`, `internal`) as the first metrics worth tracking, alongside retrieval cache hit rate, end-to-end latency, and per-stage timings.
