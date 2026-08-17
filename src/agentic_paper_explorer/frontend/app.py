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
    error_message: str | None = None

    try:
        for event in client.stream_answer(query):
            if event.event == "chunk":
                text = str(event.data.get("text", ""))
                answer_parts.append(text)
                answer_placeholder.markdown("".join(answer_parts))
            elif event.event == "error":
                error_message = str(event.data.get("message", "Answer generation failed."))
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

    if error_message:
        st.error(error_message)
    if model:
        st.caption(f"Model: {model}")
    render_sources(sources)
    _store_answer("".join(answer_parts), sources, model, error_message)


def _render_non_streaming_fallback(
    client: GenerationClient, query: str, answer_placeholder: Any
) -> None:
    try:
        response = client.answer(query)
    except GenerationClientError as exc:
        st.error(str(exc))
        return
    answer_placeholder.markdown(response.answer)
    error_message = (
        "The answer could not be generated, so no model output is shown above."
        if response.degraded
        else None
    )
    if error_message:
        st.error(error_message)
    if response.model:
        st.caption(f"Model: {response.model}")
    render_sources(response.sources)
    _store_answer(response.answer, response.sources, response.model, error_message)


def _store_answer(
    answer: str, sources: list[str], model: str | None, error_message: str | None
) -> None:
    """Keep the rendered answer so it survives the rerun triggered by a feedback click."""
    st.session_state["last_answer"] = {
        "answer": answer,
        "sources": sources,
        "model": model,
        "error": error_message,
    }


def render_stored_answer() -> None:
    """Re-render the previously generated answer after a Streamlit rerun."""
    stored = st.session_state.get("last_answer")
    if not stored:
        return
    st.markdown(stored["answer"])
    if stored["error"]:
        st.error(stored["error"])
    if stored["model"]:
        st.caption(f"Model: {stored['model']}")
    render_sources(stored["sources"])


def render_feedback(client: GenerationClient, query: str) -> None:
    """Collect a helpful/not-helpful rating with an optional comment."""
    st.divider()
    st.caption("Was this answer helpful?")
    comment = st.text_input("Optional comment", key="feedback_comment")
    helpful_column, unhelpful_column = st.columns(2)
    rating: str | None = None
    if helpful_column.button("Helpful", use_container_width=True):
        rating = "up"
    if unhelpful_column.button("Not helpful", use_container_width=True):
        rating = "down"

    if rating is None:
        return
    try:
        client.submit_feedback(query, rating, comment.strip() or None)
    except GenerationClientError as exc:
        st.warning(str(exc))
        return
    st.success("Thanks for the feedback.")


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
        st.session_state["last_query"] = query.strip()
        with st.spinner("Searching the paper context..."):
            render_answer(client, query.strip())
    else:
        render_stored_answer()

    last_query = st.session_state.get("last_query")
    if last_query and st.session_state.get("last_answer"):
        render_feedback(client, last_query)


if __name__ == "__main__":
    main()
