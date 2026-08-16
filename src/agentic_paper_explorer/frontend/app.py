"""Streamlit user interface for the Agentic Paper Explorer."""

from __future__ import annotations

from typing import Any

import streamlit as st

from agentic_paper_explorer.configs.settings import get_settings
from agentic_paper_explorer.frontend.client import GenerationClient, GenerationClientError


def render_sources(sources: list[str]) -> None:
    """Render source links returned by the generation service."""
    if not sources:
        return
    st.subheader("Sources")
    for index, source in enumerate(sources, start=1):
        st.markdown(f"{index}. [{source}]({source})")


def render_answer(client: GenerationClient, query: str) -> None:
    """Stream an answer and render its completion metadata."""
    answer_placeholder = st.empty()
    answer_parts: list[str] = []
    sources: list[str] = []
    model: str | None = None

    try:
        for event in client.stream_answer(query):
            if event.event == "chunk":
                text = str(event.data.get("text", ""))
                answer_parts.append(text)
                answer_placeholder.markdown("".join(answer_parts))
            elif event.event == "complete":
                sources = [str(source) for source in event.data.get("sources", [])]
                raw_model = event.data.get("model")
                model = str(raw_model) if raw_model is not None else None
    except GenerationClientError:
        if answer_parts:
            st.warning("The stream ended early. The partial answer is shown above.")
        else:
            _render_non_streaming_fallback(client, query, answer_placeholder)
            return

    if model:
        st.caption(f"Model: {model}")
    render_sources(sources)


def _render_non_streaming_fallback(
    client: GenerationClient, query: str, answer_placeholder: Any
) -> None:
    try:
        response = client.answer(query)
    except GenerationClientError as exc:
        st.error(str(exc))
        return
    answer_placeholder.markdown(response.answer)
    if response.model:
        st.caption(f"Model: {response.model}")
    render_sources(response.sources)


def main() -> None:
    """Render the Streamlit application."""
    st.set_page_config(page_title="Agentic Paper Explorer", layout="centered")
    st.title("Agentic Paper Explorer")
    st.write("Ask a question and explore an answer grounded in retrieved research papers.")

    backend_url = get_settings().backend_api_base_url
    client = GenerationClient(backend_url)
    query = st.text_area(
        "Research question",
        placeholder="How does retrieval improve generation?",
        height=120,
    )

    if st.button("Ask", type="primary", disabled=not query.strip(), use_container_width=True):
        st.session_state.pop("last_answer", None)
        with st.spinner("Searching the paper context..."):
            render_answer(client, query.strip())


if __name__ == "__main__":
    main()
