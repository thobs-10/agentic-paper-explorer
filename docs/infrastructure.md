# Local infrastructure

The full stack is defined in [docker-compose.yml](../docker-compose.yml) and built from the
multi-stage [Dockerfile](../Dockerfile).

| Service | Port | Role |
| --- | --- | --- |
| `frontend` | 8501 | Streamlit UI |
| `backend` | 8000 | Retrieval + generation API |
| `ingestion` | 8001 | arXiv ingestion API |
| `litellm` | 4000 | Model gateway |
| `litellm-db` | internal | LiteLLM metadata store |
| `qdrant` | 6333 / 6334 | Vector database (HTTP / gRPC) |
| `redis` | 6379 | Retrieval cache |
| `prometheus` | 9090 | Metrics scraping and storage |
| `grafana` | 3000 | Dashboards |

Start everything with:

```bash
cp .env.example .env   # then set OPENROUTER_API_KEY
docker compose up -d
```

Default local connection settings are listed in [.env.example](../.env.example).

Convenience targets are in [Makefile](../Makefile):

```bash
make infra-config   # validate the compose file
make infra-up       # start qdrant, redis, litellm only
make build          # build backend, ingestion, frontend images
make up             # start the whole stack
make ps             # show service status
make logs           # tail application logs
make down           # stop and remove services
```

Every service declares a health check, so `docker compose ps` reports readiness rather than just
container liveness. Dependencies use `condition: service_healthy`, so the backend does not start
before Qdrant, Redis, and the model gateway are actually accepting connections. Data persists in the
`qdrant_data`, `redis_data`, `litellm_pg_data`, `hf_cache`, `prometheus_data`, and `grafana_data`
named volumes; `hf_cache` is shared between the backend and ingestion containers so the embedding
model is downloaded once.

## Rebuild rules

Application source is baked into the images with `COPY src ./src` and is not bind-mounted, which has
an operational consequence worth knowing:

| Change | Action required |
| --- | --- |
| Provider API key | recreate `litellm` only |
| Model slug or other env var | recreate `litellm` and `backend` |
| Python source | **rebuild** the affected image (`docker compose up -d --build backend`) |
