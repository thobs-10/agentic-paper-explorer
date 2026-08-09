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
