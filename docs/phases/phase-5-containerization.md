# Phase 5 - Containerization and end-to-end validation

Phase 5 packages every component as a container, runs the first real end-to-end query through the
whole system, and closes the failure-visibility gaps that end-to-end testing exposed.

## What was built

| Concern | Location |
| --- | --- |
| Multi-stage build for all services | [Dockerfile](../../Dockerfile) |
| Service topology, health checks, volumes | [docker-compose.yml](../../docker-compose.yml) |
| Build context exclusions | [.dockerignore](../../.dockerignore) |
| Container and local run targets | [Makefile](../../Makefile) |
| Liveness endpoints | [backend router](../../src/agentic_paper_explorer/backend/api/router.py), [ingestion router](../../src/agentic_paper_explorer/ingestion/api/router.py) |
| Degraded-response contract | [models.py](../../src/agentic_paper_explorer/backend/api/models.py), [service.py](../../src/agentic_paper_explorer/backend/generation/service.py) |
| Empty-response guard | [provider.py](../../src/agentic_paper_explorer/backend/generation/provider.py) |

## Image layout

The Dockerfile uses one shared runtime base and three service targets (`backend`, `ingestion`,
`frontend`). Dependency layers are resolved per service with `uv sync --extra <service>`, so the
frontend image does not carry the embedding or vector-store stack. Only lock metadata is copied
before dependency resolution, which keeps dependency layers cached when application source changes.
All services run as a non-root `app` user, and the Hugging Face cache directory is created and owned
in the image so the named volume mount does not end up root-owned.

Application source is baked in with `COPY src ./src` and is not bind-mounted, which has an
operational consequence worth knowing:

| Change | Action required |
| --- | --- |
| Provider API key | recreate `litellm` only |
| Model slug or other env var | recreate `litellm` and `backend` |
| Python source | **rebuild** the affected image (`docker compose up -d --build backend`) |

## Request flow

An end-to-end request moves through the system as follows. Ingestion is a separate service and is
not triggered by a query; the backend answers from whatever is already stored in Qdrant.

```text
Streamlit UI
  -> POST /api/v1/generation/answer
     -> Redis lookup (key: prompt:<normalized-slug>)
        -> on miss: embed query -> Qdrant top-k search -> cache the ranked chunks
     -> GenerationService builds the citation-aware prompt
        -> LiteLLM gateway -> model provider
  <- answer + sources + model + degraded flag
```

## Failure visibility

End-to-end testing showed that a misconfigured model gateway returned `HTTP 200` with a friendly
fallback sentence, which made an operator-level outage look like a normal answer. Generation
failures are now explicit:

- `GenerationResult` and `GenerationResponse` carry `degraded: bool` and `error_category: str | None`.
- The JSON endpoint returns **HTTP 502** when generation is degraded, while still returning the
  retrieved `sources` so the client can show traceable context.
- The streaming endpoint emits a dedicated `error` event with the failure category, then terminates
  with `complete` carrying `degraded` and `error_category`.
- Retrieval abstention is *not* treated as degraded. Missing evidence is a valid answer; a broken
  provider is not.

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

## Empty model responses

Reasoning-oriented models return their text in a separate `reasoning` field and leave
`message.content` empty. Reading only `content` would have produced blank answers with `HTTP 200`,
which is the same class of silent failure as above. The provider now raises
`ProviderError(category="empty_response", retryable=False)` when a completion or a stream yields no
usable content, so it flows into the degraded path. `_classify_provider_error` also passes existing
`ProviderError` instances through unchanged, so the category is not lost when the error is raised
inside the retry block.

The default model is `openrouter/google/gemma-4-26b-a4b-it:free`, which returns standard message
content. When changing models, verify the candidate populates `message.content` rather than only
`reasoning`.

## Verification

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

Observed on a corpus of 4192 chunks: cold request `HTTP 200` in ~20s returning a cited answer with 5
sources, streaming delivering token-level deltas, and `HTTP 502` with `error_category: "upstream"`
when the gateway is stopped.

Full suite:

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run ruff format --check src tests
```

## Operational notes

- **Redis caches retrieval, not answers.** A repeated query still calls the model; only the
  embedding and vector search are skipped. Answer caching is a separate decision.
- **The corpus must be populated first.** A query against an empty collection returns the abstention
  message, not an error. Load data with `POST /api/v1/ingestion/papers/process` on port 8001.
- **Integration tests create and drop their own Qdrant collections.** Interrupted runs can leave
  `integration-test-*` collections behind; delete them directly if they accumulate.

## Known follow-ups

- no metrics, traces, or dashboards yet, so latency and failure categories are only visible in
  container logs — *resolved in [Phase 6](phase-6-monitoring.md)*
- `degraded` and `error_category` are returned to clients but not yet exported as monitoring signals
  — *resolved in [Phase 6](phase-6-monitoring.md)*
- Qdrant client and server versions differ enough to emit a compatibility warning and should be
  pinned
- answer-level caching and a hybrid retrieval pass remain open from earlier phases
