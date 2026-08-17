.PHONY: infra-config infra-up infra-down infra-logs infra-ps up down logs ps build api ingest ui

infra-config:
	docker compose config

infra-up:
	docker compose up -d qdrant redis litellm

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f qdrant redis litellm

infra-ps:
	docker compose ps

build:
	docker compose build backend ingestion frontend

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f backend ingestion frontend

ps:
	docker compose ps

api:
	uv run uvicorn agentic_paper_explorer.backend.api.router:app --reload

ingest:
	uv run uvicorn agentic_paper_explorer.ingestion.api.router:app --reload --port 8001

ui:
	uv run streamlit run src/agentic_paper_explorer/frontend/app.py
