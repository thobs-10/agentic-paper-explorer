# Phase 4 - Streamlit UI

The Streamlit frontend lives under [frontend](../../src/agentic_paper_explorer/frontend) and uses
the generation API through a small testable HTTP client.

| Concern | Location |
| --- | --- |
| Views and session state | [app.py](../../src/agentic_paper_explorer/frontend/app.py) |
| Backend HTTP client | [client.py](../../src/agentic_paper_explorer/frontend/client.py) |
| Client tests | [test_client.py](../../tests/frontend/test_client.py) |

Start the backend and UI in separate terminals:

```bash
uv run uvicorn agentic_paper_explorer.backend.api.router:app --reload
uv run streamlit run src/agentic_paper_explorer/frontend/app.py
```

The UI opens at `http://localhost:8501`. Configure another backend with:

```text
BACKEND_API_BASE_URL=http://localhost:8000
```

Behavior:

- streams answer chunks by default and renders them incrementally
- displays the final sources and model metadata after the `complete` event
- warns when a stream ends after partial output
- falls back to the complete JSON endpoint when streaming cannot start
- shows insufficient retrieval context as a normal abstention state rather than a transport error

All data fetching stays inside `client.py`, so the view layer holds no HTTP logic and the client can
be tested without running Streamlit.
