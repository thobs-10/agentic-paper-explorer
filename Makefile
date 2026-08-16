.PHONY: infra-config infra-up infra-down infra-logs infra-ps api ui

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

api:
	uv run uvicorn agentic_paper_explorer.backend.api.router:app --reload

ui:
	uv run streamlit run src/agentic_paper_explorer/frontend/app.py
