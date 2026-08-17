# Phase 2 - Retrieval and cached context assembly

Phase 2 introduces the retrieval layer used to turn a user prompt into ranked paper chunks before
generation. The current implementation is intentionally a pragmatic baseline: fast Redis lookup
first, then semantic search in Qdrant, then context packaging for the next generation stage.

## What was built

| Concern | Location |
| --- | --- |
| Retrieval orchestration service | [service.py](../../src/agentic_paper_explorer/backend/retrieval/service.py) |
| Qdrant similarity search contract | [qdrant_client.py](../../src/agentic_paper_explorer/backend/database/qdrant_client.py) |
| Retrieval regression tests | [test_retrieval_service.py](../../tests/backend/retrieval/test_retrieval_service.py) |

## Retrieval behavior

The retrieval service currently follows this flow:

1. normalize the prompt into a cache key
2. look up cached results in Redis
3. on a miss, embed the query with the configured embedding function
4. search the Qdrant collection for top-k semantic matches
5. filter matches by the configured score threshold
6. map payloads into `RetrievedChunk` objects with paper metadata and source URLs
7. store the final ranked context back in Redis with a TTL for repeated queries

This gives a strong latency win for repeated prompts while still supporting semantic search when no
cached result exists.

## Current design choices

The phase is deliberately scoped to a cache-first + semantic retrieval pattern rather than a full
hybrid retrieval stack:

- Redis is used as a prompt-result cache to reduce repeated vector-search cost.
- Qdrant remains the semantic retrieval backend for similarity search over embedded chunk vectors.
- ranking is handled by the score returned from Qdrant, with lightweight filtering before packaging.
- the cached payload preserves the prompt and the chunk list in a compact, generation-ready shape.

This is a sound milestone for the project, but it is not yet a full hybrid retrieval system with
lexical matching, multi-source merging, or reranking across multiple retrieval strategies.

## Deferred enhancements

- lexical search or BM25-style retrieval for exact-term recall
- hybrid result merging across semantic and lexical signals
- reranking of combined results before final context assembly
- richer Redis metadata, including versioning and invalidation keys

## Verification

```bash
uv run pytest tests/backend/retrieval/test_retrieval_service.py -q
uv run ruff check src/agentic_paper_explorer/backend/retrieval/service.py src/agentic_paper_explorer/backend/database/qdrant_client.py
```

This keeps the retrieval phase testable and isolated while leaving room for the response-generation
layer to build on top of the resulting context bundle.
