# Phase 0 - Datastores and the arXiv read API

Phase 0 delivers the local datastores plus a typed, batched read path over the public arXiv Atom
API. No data is written to Qdrant yet; that begins in [Phase 1](phase-1-ingestion-pipeline.md).

## What was built

| Concern | Location |
| --- | --- |
| arXiv HTTP client and Atom parsing | [arxiv_client.py](../../src/agentic_paper_explorer/ingestion/data_ingestion/arxiv_client.py) |
| Request and response contracts | [models.py](../../src/agentic_paper_explorer/ingestion/api/models.py) |
| FastAPI app and route | [router.py](../../src/agentic_paper_explorer/ingestion/api/router.py) |
| Tests mirroring the source tree | [tests/ingestion](../../tests/ingestion) |

## arXiv client

`ArxivClient` wraps `https://export.arxiv.org/api/query` and returns normalized records instead of
raw XML.

- `search_papers(search_query, start, max_results)` is the async entry point. The underlying `httpx`
  call is synchronous and is offloaded with `asyncio.to_thread`, so the FastAPI event loop is never
  blocked.
- Responses are parsed with `defusedxml` rather than the stdlib XML parser, to avoid
  entity-expansion and external-entity attacks on untrusted feed content.
- Parsing returns two frozen, slotted dataclasses:
  - `ArxivPaperRecord` - one paper (id, title, summary, published/updated timestamps, authors,
    categories, primary category, comment, journal reference, PDF link, entry link).
  - `ArxivSearchResult` - the page envelope (`total_results`, `start_index`, `items_per_page`,
    `papers`).
- Text fields are whitespace-normalized, and optional fields collapse to `None` when blank, so
  downstream chunking and embedding do not have to re-clean the data.
- Parsing is exposed as a pure static method (`parse_search_response`), which keeps it testable
  without network access.

## Batched fetching model

arXiv paginates through an offset window rather than a cursor, so batching is expressed as `start`
plus `max_results`:

- `start` - zero-based offset of the first record in the batch (`ge=0`).
- `max_results` - batch size, bounded to `1..100` to stay within arXiv's practical page limit and to
  cap memory and latency per request.
- `total_results` in the response tells the caller how many batches remain, so a pipeline can walk
  pages by advancing `start` by `max_results` until `start >= total_results`.

Bounds are enforced twice on purpose: at the FastAPI query layer (fast rejection with HTTP 422) and
in the Pydantic model (protects any non-HTTP caller of the same contract).

## REST endpoint

```text
GET /api/v1/ingestion/papers/search?search_query=all:llm&start=0&max_results=10
```

- Query parameters are normalized into `ArxivSearchRequest` through a `Depends` factory, keeping the
  handler free of parameter parsing.
- `ArxivClient` is injected through `get_arxiv_client`, so tests can override the dependency instead
  of patching module globals.
- The handler stays thin: call the client, map the dataclasses onto `ArxivPaperResponse` via
  `model_validate(..., from_attributes=True)`, return `ArxivSearchResponse`.
- Upstream failures (timeouts, non-2xx from arXiv, malformed feeds) are translated into HTTP 502
  with a generic message, so upstream internals are not leaked to clients.

Run the API locally:

```bash
uv run uvicorn agentic_paper_explorer.ingestion.api.router:app --reload
```

Interactive docs are then available at `http://localhost:8000/docs`.

Example request:

```bash
curl "http://localhost:8000/api/v1/ingestion/papers/search?search_query=all:retrieval%20augmented%20generation&start=0&max_results=5"
```

## Verification

```bash
uv run pytest tests/ingestion
uv run ruff check .
uv run bandit -r src
```

Tests cover Atom parsing, offload to `asyncio.to_thread`, request URL construction, the bounded
success path, and the 502 upstream-failure path. All external HTTP calls are mocked, so the suite is
deterministic and offline.

## Hardening

Before Phase 1 ingestion pipelines were built, the following gaps were closed:

- CORS origins are now read from `ALLOWED_ORIGINS` via
  [settings.py](../../src/agentic_paper_explorer/configs/settings.py) instead of a hardcoded
  wildcard.
- `ArxivClient` reuses one pooled `httpx.Client` for its lifetime (created once via a FastAPI
  `lifespan` hook in [router.py](../../src/agentic_paper_explorer/ingestion/api/router.py)) instead
  of opening a new client per request.
- Requests to arXiv are rate-limited (`ARXIV_MIN_REQUEST_INTERVAL_SECONDS`, default 3s) and retried
  with exponential backoff on transient 5xx/timeout responses (`ARXIV_MAX_RETRIES`,
  `ARXIV_RETRY_BACKOFF_SECONDS`).
