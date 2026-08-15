"""LiteLLM-backed provider adapter used by the generation service."""

from __future__ import annotations


class LiteLLMProvider:
    """Thin adapter for LiteLLM completion calls."""

    def __init__(
        self,
        *,
        model: str,
        api_base: str,
        api_key: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> None:
        self._model = model
        self._api_base = api_base
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Call LiteLLM and return the model text content."""
        try:
            import litellm
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "LiteLLM is not installed. Add it to the project dependencies."
            ) from exc

        response = await litellm.acompletion(
            model=self._model,
            api_base=self._api_base,
            api_key=self._api_key,
            messages=[
                {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature if temperature is not None else self._temperature,
            max_tokens=self._max_tokens,
        )

        choices = getattr(response, "choices", [])
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", "")
        return str(content or "")
