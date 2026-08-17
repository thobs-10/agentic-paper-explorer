# Phase 6 - Monitoring, user feedback, and Grafana dashboard

Phase 6 closes the observability gap left by [Phase 5](phase-5-containerization.md). The backend now
exports Prometheus metrics, the UI collects a helpful/not-helpful rating on every answer, and a
provisioned Grafana dashboard turns both into operational signal.

The scope is deliberately narrow: metrics only, no tracing backend. Adding OpenTelemetry plus a
collector would have introduced two more moving parts for signals nothing currently consumes, so the
phase uses `prometheus-client` directly and leaves distributed tracing as a later decision.

## What was built

| Concern | Location |
| --- | --- |
| Metric definitions and FastAPI instrumentation | [metrics.py](../../src/agentic_paper_explorer/monitoring/metrics.py) |
| Feedback recording logic | [feedback.py](../../src/agentic_paper_explorer/monitoring/feedback.py) |
| Feedback contract and endpoint | [models.py](../../src/agentic_paper_explorer/backend/api/models.py), [router.py](../../src/agentic_paper_explorer/backend/api/router.py) |
| Feedback submission from the UI | [client.py](../../src/agentic_paper_explorer/frontend/client.py), [app.py](../../src/agentic_paper_explorer/frontend/app.py) |
| Scrape and provisioning config | [monitoring/configs](../../src/agentic_paper_explorer/monitoring/configs) |
| Dashboard definition | [rag_overview.json](../../src/agentic_paper_explorer/monitoring/configs/grafana/dashboards/rag_overview.json) |
| Monitoring service topology | [docker-compose.yml](../../docker-compose.yml) |
| Tests | [tests/monitoring](../../tests/monitoring), [test_feedback_router.py](../../tests/backend/api/test_feedback_router.py) |

## Services

| Service | Port | Role |
| --- | --- | --- |
| `prometheus` | 9090 | Scrapes `backend:8000/metrics` every 15s, 15 day retention |
| `grafana` | 3000 | Provisioned datasource and dashboard, anonymous sign-up disabled |

Grafana credentials default to `admin` / `admin` for local use and are overridable with
`GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`. Change them before exposing the stack anywhere
but localhost.

## Metrics

[metrics.py](../../src/agentic_paper_explorer/monitoring/metrics.py) is the only module that imports
`prometheus_client`. Everything else records telemetry through three small functions
(`record_answer`, `record_retrieval`, `record_feedback`) rather than holding collector references,
which keeps the metric names in one place and the call sites trivial to read.

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `rag_answer_requests_total` | counter | `endpoint`, `outcome` | Answers served, split by `answer`/`stream` and `ok`/`degraded` |
| `rag_llm_errors_total` | counter | `category` | Provider failures using the Phase 5 error categories |
| `rag_retrieval_cache_total` | counter | `result` | Redis `hit` versus `miss` on the retrieval cache |
| `rag_retrieval_chunks` | histogram | - | Context chunks returned per query |
| `rag_feedback_total` | counter | `rating` | User ratings, `up` or `down` |

HTTP throughput and latency (`http_requests_total`, `http_request_duration_seconds`) come from
`prometheus-fastapi-instrumentator`, so no hand-rolled timing middleware was needed. `/health` and
`/metrics` are excluded from those series to stop health-check traffic from dominating the request
rate.

Two deliberate details:

- **Label values are pre-initialised to zero.** Prometheus does not emit a series until it is first
  touched, so a fresh deployment would render empty panels and `NaN` ratios. Creating the label
  combinations at startup means the dashboard is readable before the first request.
- **Instrumentation sits in the route handlers, not the services.** `RetrievalService` and
  `GenerationService` stay free of any monitoring dependency and remain testable without a metrics
  registry. The cost is three lines per handler.

## User feedback

```text
POST /api/v1/feedback
Content-Type: application/json

{"query":"How does retrieval improve generation?","rating":"up","comment":"Clear and cited"}
```

Returns `201` with `{"status":"recorded","rating":"up"}`.

- `rating` is typed as `Literal["up","down"]` and the query and comment are length-capped in the
  Pydantic model, so malformed input is rejected at the boundary with `HTTP 422` before reaching any
  logic.
- Feedback is recorded as a counter only. There is no persistence layer in this phase, which keeps
  the path free of a schema, a migration, and a failure mode. The trade-off is that free-text
  comments are not queryable later; that is a deliberate deferral, not an oversight.
- The comment body is never logged. Only the rating, a truncated query, and a `has_comment` boolean
  are emitted, so user-supplied text does not leak into container logs.

In the UI, **Helpful** and **Not helpful** buttons appear beneath each answer with an optional
comment field. Clicking a button triggers a Streamlit rerun, so the rendered answer is cached in
`session_state` and re-rendered rather than disappearing.

## Dashboard

Provisioned automatically at `http://localhost:3000` as **Agentic Paper Explorer - RAG Overview**:

| Panel | Signal |
| --- | --- |
| Request rate by endpoint | Throughput per handler |
| Request latency (p50 / p95) | Tail latency from the histogram buckets |
| Degraded answer rate | Percentage of answers hitting the Phase 5 degraded path |
| Answer satisfaction | Percentage of ratings that were helpful |
| Retrieval cache hit ratio | Redis effectiveness against vector-search cost |
| User feedback over time | Helpful versus not-helpful volume |
| LLM errors by category | Which failure category is actually firing |
| Retrieved chunks per query | Average context depth, from the histogram |

Ratio panels divide by `clamp_min(..., 1)` so an idle system shows `0%` instead of `NaN`.

## Verification

```bash
docker compose up -d --build backend frontend
docker compose up -d prometheus grafana

curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/metrics        # expect 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/api/v1/feedback \
  -H 'Content-Type: application/json' -d '{"query":"smoke test","rating":"up"}'  # expect 201

# scrape target should report "up"
curl -s 'http://localhost:9090/api/v1/targets?state=active' | python3 -m json.tool | grep -A1 '"health"'

# counter should be visible in Prometheus
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=rag_feedback_total' | python3 -m json.tool
```

Then open `http://localhost:3000` and select the RAG Overview dashboard.

Test suite:

```bash
uv run pytest tests/monitoring tests/backend/api -q
uv run ruff check src tests
```

Metric tests assert on before/after deltas read through `REGISTRY.get_sample_value` rather than
absolute values, so they stay isolated under `pytest-randomly` despite the shared process-wide
registry.

## Operational notes

- **Rebuild after source changes.** `src/` is baked into the images, so metric or endpoint changes
  need `docker compose up -d --build backend frontend`. A stale image shows up as a Prometheus
  target `down` with a `404` on `/metrics`.
- **Rate-based panels need warm-up.** `rate()` and `increase()` panels need a few scrape intervals
  plus real traffic before they draw a line. The stat and gauge panels read raw counters and
  populate immediately.
- **Metrics are per-process and in-memory.** A backend restart resets the counters, and running
  multiple backend replicas would need a shared registry or per-instance aggregation in PromQL.

## Known follow-ups

- feedback comments are counted but not stored, so qualitative review is not possible yet
- no alerting rules are defined; the dashboard is read-only observation
- no tracing, so per-stage latency within a request is still not attributable
- Qdrant client and server versions differ enough to emit a compatibility warning and should be
  pinned
- answer-level caching and a hybrid retrieval pass remain open from earlier phases
