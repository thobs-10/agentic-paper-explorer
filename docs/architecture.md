# Architecture

Agentic Paper Explorer is a retrieval-augmented generation (RAG) system over arXiv papers. It is
split into two independent write and read paths:

- **Ingestion (write path)** - fetch arXiv metadata, chunk it, embed it, store vectors in Qdrant.
- **Query (read path)** - embed a user prompt, retrieve ranked chunks, generate a cited answer.

The two paths share only the vector store, so ingestion can run, fail, or scale without affecting
the query API.

> Diagram images exported from these definitions can be placed in [images](images) and embedded
> alongside the Mermaid source.

## System context

```mermaid
flowchart LR
    user([User])
    arxiv([arXiv Atom API])
    provider([Model provider])

    subgraph app[Agentic Paper Explorer]
        frontend[Streamlit UI<br/>:8501]
        backend[Backend API<br/>:8000]
        ingestion[Ingestion API<br/>:8001]
        litellm[LiteLLM gateway<br/>:4000]
        qdrant[(Qdrant<br/>vectors)]
        redis[(Redis<br/>retrieval cache)]
        prometheus[(Prometheus)]
        grafana[Grafana<br/>:3000]
    end

    user --> frontend --> backend
    backend --> redis
    backend --> qdrant
    backend --> litellm --> provider
    ingestion --> arxiv
    ingestion --> qdrant
    prometheus -- scrape /metrics --> backend
    grafana --> prometheus
```

## Component layout

Every module under `src/agentic_paper_explorer` owns one concern, and framework glue stays out of
the business logic.

```mermaid
flowchart TB
    subgraph frontend[frontend]
        app[app.py<br/>Streamlit views]
        client[client.py<br/>HTTP client]
    end

    subgraph backendmod[backend]
        api[api/<br/>routers + Pydantic models]
        retrieval[retrieval/<br/>RetrievalService]
        generation[generation/<br/>provider, prompts, service]
        database[database/<br/>Qdrant + Redis clients]
    end

    subgraph ingestionmod[ingestion]
        iapi[api/<br/>router + models]
        pipeline[pipeline.py]
        dataing[data_ingestion/<br/>arxiv_client, batch_reader]
        processing[processing/<br/>chunking, embeddings]
    end

    subgraph shared[shared]
        configs[configs/settings.py]
        monitoring[monitoring/<br/>metrics, feedback]
        utils[utils/]
    end

    app --> client --> api
    api --> retrieval --> database
    api --> generation
    api --> monitoring
    iapi --> pipeline --> dataing
    pipeline --> processing
    pipeline --> database
    backendmod --> configs
    ingestionmod --> configs
```

Design rules the layout enforces:

- Route handlers stay thin. They parse the contract, call a service, and map the result.
- Services take their collaborators by injection, so tests never patch module globals.
- Only `monitoring/metrics.py` imports `prometheus_client`; services stay free of telemetry deps.
- Only `generation/provider.py` talks to LiteLLM, so provider quirks stay in one file.

## Query request flow

```mermaid
sequenceDiagram
    participant U as Streamlit UI
    participant A as Backend API
    participant R as RetrievalService
    participant C as Redis
    participant Q as Qdrant
    participant G as GenerationService
    participant L as LiteLLM

    U->>A: POST /api/v1/generation/answer
    A->>R: retrieve(query)
    R->>C: GET prompt:<normalized-slug>
    alt cache hit
        C-->>R: ranked chunks
    else cache miss
        R->>R: embed(query)
        R->>Q: top-k vector search
        Q-->>R: scored payloads
        R->>C: SET ranked chunks (TTL)
    end
    R-->>A: RetrievedChunk[]
    alt no usable context
        A-->>U: deterministic abstention + sources
    else context available
        A->>G: generate(query, chunks)
        G->>L: citation-aware prompt
        L-->>G: answer text
        G-->>A: answer + sources + degraded flag
        A-->>U: 200 answer, or 502 when degraded
    end
```

Failure semantics worth remembering:

- **Abstention is not failure.** Missing evidence returns `HTTP 200` with the abstention message.
- **A broken provider is failure.** It returns `HTTP 502` with `degraded: true` and an
  `error_category`, while still returning retrieved sources.

## Ingestion flow

```mermaid
flowchart LR
    trigger[POST /api/v1/ingestion/papers/process] --> reader
    reader[batch_reader<br/>paged start + max_results] --> arxiv[(arXiv Atom API)]
    arxiv --> normalize[ArxivPaperRecord<br/>normalized fields]
    normalize --> chunk[chunking<br/>windows with overlap]
    chunk --> embed[embeddings<br/>Hugging Face model]
    embed --> ensure[ensure collection]
    ensure --> upsert[upsert deterministic point IDs]
    upsert --> qdrant[(Qdrant)]
    upsert --> summary[papers + chunks summary]
```

Deterministic point IDs make repeated ingests idempotent, so re-running a query updates existing
points instead of duplicating the corpus.

## Deployment topology

```mermaid
flowchart TB
    subgraph compose[docker compose]
        fe[frontend<br/>:8501]
        be[backend<br/>:8000]
        ing[ingestion<br/>:8001]
        lite[litellm<br/>:4000]
        litedb[(litellm-db)]
        qd[(qdrant<br/>:6333/:6334)]
        rd[(redis<br/>:6379)]
        prom[(prometheus<br/>:9090)]
        graf[grafana<br/>:3000]
    end

    fe --> be
    be --> qd
    be --> rd
    be --> lite
    lite --> litedb
    ing --> qd
    prom --> be
    graf --> prom
```

All services declare health checks and depend on each other with `condition: service_healthy`, so
the backend never starts before Qdrant, Redis, and the gateway accept connections. State lives in
named volumes: `qdrant_data`, `redis_data`, `litellm_pg_data`, `hf_cache`, `prometheus_data`, and
`grafana_data`.

## Cross-cutting decisions

| Decision | Rationale |
| --- | --- |
| Cache-first retrieval | Redis removes repeated embedding and vector-search cost for hot prompts |
| Citation-aware prompting | Every claim is traceable to a retrieved excerpt marker |
| Explicit degraded contract | A gateway outage must not look like a normal answer |
| Metrics only, no tracing backend | Fewer moving parts for signals nothing yet consumes |
| Per-service dependency extras | Frontend images do not carry the embedding or vector stack |
| Environment-driven configuration | No hardcoded secrets or environment-specific endpoints |
