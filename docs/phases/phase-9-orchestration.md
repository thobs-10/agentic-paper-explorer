# Phase 9 - Ingestion orchestration (planned, priority 3)

`project.md` names ZenML, Hamilton, or Prefect as candidates and defers the choice. This phase makes
the choice and wires it into the one pipeline that needs it today:
[pipeline.py](../../src/agentic_paper_explorer/ingestion/pipeline.py).

## Why priority 3

Guardrails (Phase 8) protect the query path, which is user-facing and higher risk. Orchestration
protects the ingestion path, which already has retry/backoff logic
(`arxiv_max_retries`, `arxiv_retry_backoff_seconds`) but no run history, no scheduling, and no
visibility into a partially-failed batch beyond application logs.

## Tool choice

**Prefect** (open source core, Apache-2.0), run as a single additional `worker` process/container
alongside the existing services.

| Option | Trade-off for this project |
| --- | --- |
| **Prefect** (chosen) | Decorate existing async functions with `@flow` / `@task`; keeps `run_ingestion_pipeline` and its helpers almost unchanged. Ships a local UI (`prefect server`) for run history, retries, and scheduling with no extra query language to learn. |
| ZenML | Optimized for ML training pipelines (model registries, artifact stores); the ingestion pipeline here is closer to a data ETL job, so ZenML's MLOps surface is mostly unused weight. |
| Hamilton | Excellent for declarative dataframe/feature pipelines, but the pipeline here is I/O-bound (HTTP fetch, embed, upsert) and imperative already; Hamilton's function-as-node model would force more restructuring than Prefect's decorator approach. |

Prefect is the best fit against the project's own bar: "easiest to integrate with the existing
codebase and maintainability."

## What to build

| Concern | Location |
| --- | --- |
| Flow/task decorators over existing pipeline functions | `src/agentic_paper_explorer/backend/pipelines/ingestion_flow.py` (new; the empty `pipelines/` package already exists for this) |
| Scheduled/triggered runs | Prefect deployment definition, `src/agentic_paper_explorer/backend/pipelines/deployment.py` |
| Local orchestration service | `docker-compose.yml` - add a `prefect-server` service (SQLite-backed for local use, no extra DB) |
| Settings for Prefect API URL | `configs/settings.py` - `PREFECT_API_URL`, env-driven |
| Tests | `tests/backend/pipelines/test_ingestion_flow.py` (new), asserting task composition and retry behavior with mocked collaborators |

## Design approach

- Wrap the existing `run_ingestion_pipeline` body with `@flow`, and turn the per-page steps
  (fetch page, chunk, embed, upsert) into `@task`s so Prefect's UI shows per-stage duration and
  failures instead of one opaque function call.
- Keep the existing `IngestionSummary` return type - orchestration wraps the pipeline, it does not
  change its contract.
- The ingestion FastAPI endpoint (`POST /api/v1/ingestion/papers/process`) keeps calling the pipeline
  directly for synchronous requests; Prefect is additive for scheduled/batch runs, not a replacement
  for the existing on-demand endpoint.

## Concrete steps

1. Add `prefect` to the `ingestion` optional-dependency group.
2. Decorate `run_ingestion_pipeline` and its per-page steps with `@flow` / `@task`, keeping the
   function signatures unchanged so existing tests and the FastAPI route need no changes.
3. Add a local `prefect-server` service to `docker-compose.yml` (SQLite backend, no extra volume
   needed beyond one for run history) so flow runs are visible without a hosted account.
4. Add a scheduled deployment (for example, nightly ingestion for a fixed set of search queries) as
   a follow-up once the flow itself is proven in a manual run.
5. Extend `monitoring/metrics.py` with pipeline-level counters (`rag_ingestion_runs_total{outcome}`)
   if Prefect's own UI does not cover what the Grafana dashboard needs.
