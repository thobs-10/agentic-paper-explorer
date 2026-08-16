"""LiteLLM-backed provider adapter used by the generation service."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Normalized error raised when a model provider call cannot complete."""

    def __init__(self, message: str, *, category: str, retryable: bool) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


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
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._model = model
        self._api_base = api_base
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

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

        request_kwargs = {
            "model": self._model,
            "api_base": self._api_base,
            "api_key": self._api_key,
            "messages": [
                {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature if temperature is not None else self._temperature,
            "max_tokens": self._max_tokens,
        }

        for attempt in range(self._max_retries + 1):
            try:
                logger.info(
                    "Starting LiteLLM generation model=%s attempt=%d",
                    self._model,
                    attempt + 1,
                )
                response = await asyncio.wait_for(
                    litellm.acompletion(**request_kwargs), timeout=self._timeout_seconds
                )
                break
            except Exception as exc:
                error = _classify_provider_error(exc)
                logger.warning(
                    "LiteLLM generation failed model=%s attempt=%d category=%s retryable=%s",
                    self._model,
                    attempt + 1,
                    error.category,
                    error.retryable,
                )
                if not error.retryable or attempt >= self._max_retries:
                    raise error from exc
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))

        choices = getattr(response, "choices", [])
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", "")
        return str(content or "")


def _classify_provider_error(exc: Exception) -> ProviderError:
    """Map provider exceptions to stable categories and retry decisions."""
    status_code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    exception_name = type(exc).__name__.lower()
    message = str(exc) or "LiteLLM provider request failed"

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in exception_name:
        return ProviderError(message, category="timeout", retryable=True)
    if status_code == 429 or "ratelimit" in exception_name or "rate_limit" in message.lower():
        return ProviderError(message, category="rate_limit", retryable=True)
    if isinstance(status_code, int) and status_code >= 500:
        return ProviderError(message, category="upstream", retryable=True)
    if isinstance(exc, (ConnectionError, OSError)) or any(
        marker in exception_name for marker in ("connection", "network")
    ):
        return ProviderError(message, category="network", retryable=True)
    return ProviderError(message, category="provider", retryable=False)
