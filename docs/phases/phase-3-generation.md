# Phase 3 - Grounded response generation

Phase 3 adds grounded response generation through the LiteLLM gateway. The application uses the
configured lightweight open-source model and keeps provider-specific calls behind
[provider.py](../../src/agentic_paper_explorer/backend/generation/provider.py).

## Reliability policy

- Each provider call has a bounded timeout controlled by `LITELLM_TIMEOUT_SECONDS` (default 30
  seconds).
- Rate limits (`429`), upstream server failures (`5xx`), timeouts, and network failures are retried
  with exponential backoff. The defaults are two retries and a 0.5 second initial delay.
- Non-transient provider errors, such as invalid requests, are not retried.
- Provider exceptions are mapped to stable categories (`rate_limit`, `upstream`, `timeout`,
  `network`, `empty_response`, or `provider`) and detailed provider messages are kept out of the API
  response.
- When all attempts fail, the generation service returns a concise fallback message and preserves
  the retrieved paper source links so the client still has traceable context. Since
  [Phase 5](phase-5-containerization.md) the response is also flagged `degraded` and returned with
  HTTP 502.
- Provider attempts and failure categories are emitted through the module logger for operational
  tracing.

The policy is configured with:

```text
LITELLM_TIMEOUT_SECONDS=30.0
LITELLM_MAX_RETRIES=2
LITELLM_RETRY_BACKOFF_SECONDS=0.5
```

### Verification

```bash
uv run pytest tests/backend/generation tests/configs/test_settings.py -q
uv run ruff check src/agentic_paper_explorer/backend/generation src/agentic_paper_explorer/configs/settings.py tests/backend/generation tests/configs/test_settings.py
```

## Grounded prompting and citations

The generation layer uses a citation-aware prompt contract so responses remain traceable to
retrieved paper excerpts.

### Answer contract

- Context chunks are ordered by descending retrieval score before they are sent to the provider.
- Each chunk receives a stable marker such as `[1]` and includes its title, source URL or paper ID,
  and excerpt text.
- Every material claim should cite the supporting marker immediately, for example:
  `The method improves recall [1].`
- The provider must use only the supplied excerpts and must not invent claims, citations, URLs, or
  marker numbers.
- The answer should begin with a concise direct response, followed by brief evidence or limitations
  when useful.
- The API returns unique source URLs separately in the `sources` field; the model is instructed not
  to add a separate references section.

### Insufficient context

When retrieval returns no usable text, generation abstains before calling the provider and returns:

```text
I do not have enough retrieved paper context to answer this question reliably.
```

The response still includes any available source URLs. This prevents an LLM from guessing when
retrieval did not provide enough evidence.

### Verification

```bash
uv run pytest tests/backend/generation/test_generation_service.py -q
```

## Streaming generation

The streaming endpoint exposes the same grounded generation flow over Server-Sent Events (SSE). The
existing JSON endpoint remains available when a client needs one complete response.

### Endpoint

```text
POST /api/v1/generation/answer/stream
Content-Type: application/json
Accept: text/event-stream
```

Request body:

```json
{"query":"How does retrieval improve generation?"}
```

The stream emits three event types:

```text
event: start
data: {"query":"How does retrieval improve generation?"}

event: chunk
data: {"text":"Retrieval provides "}

event: complete
data: {"sources":["https://arxiv.org/abs/example"],"model":"..."}
```

- `start` identifies the query.
- `chunk` contains a partial text delta and may occur many times. Clients should append `text`
  values in order.
- `complete` is the terminal event and contains the unique source URLs and model name, plus
  `degraded` and `error_category` since Phase 5.
- If retrieval has no usable context, the stream emits the deterministic abstention message as one
  `chunk`, followed by `complete`, without calling the provider.
- If the provider fails after retries, the stream emits an `error` event carrying the failure
  category and still terminates with `complete`. Clients can continue displaying already received
  partial output.

For clients that do not support SSE, use `POST /api/v1/generation/answer`, which returns the
complete `GenerationResponse` JSON contract.

### Verification

```bash
uv run pytest tests/backend/generation tests/backend/api/test_generation_router.py -q
```
