.PHONY: infra-config infra-up infra-down infra-logs infra-ps ui

infra-config:
	docker compose config

infra-up:
	docker compose up -d qdrant redis

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f qdrant redis

infra-ps:
	docker compose ps

ui:
	uv run streamlit run src/agentic_paper_explorer/frontend/app.py
