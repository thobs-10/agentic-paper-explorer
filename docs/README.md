# Documentation

In-depth documentation for Agentic Paper Explorer. The root [README.md](../README.md) is the short
overview; everything here is the detailed engineering record.

## Contents

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | System, request, ingestion, and deployment diagrams |
| [infrastructure.md](infrastructure.md) | Local service topology, ports, volumes, make targets |
| [releasing.md](releasing.md) | How to cut a tagged release and publish images to Docker Hub |
| [phases/phase-0-datastores-and-arxiv-api.md](phases/phase-0-datastores-and-arxiv-api.md) | Datastores and the batched arXiv read API |
| [phases/phase-1-ingestion-pipeline.md](phases/phase-1-ingestion-pipeline.md) | Chunking, embedding, and Qdrant upserts |
| [phases/phase-2-retrieval.md](phases/phase-2-retrieval.md) | Cache-first retrieval and context assembly |
| [phases/phase-3-generation.md](phases/phase-3-generation.md) | Grounded generation, citations, streaming |
| [phases/phase-4-streamlit-ui.md](phases/phase-4-streamlit-ui.md) | Streamlit frontend |
| [phases/phase-5-containerization.md](phases/phase-5-containerization.md) | Images, compose topology, end-to-end validation |
| [phases/phase-6-monitoring.md](phases/phase-6-monitoring.md) | Metrics, feedback, Grafana dashboard |
| [phases/phase-7-cicd.md](phases/phase-7-cicd.md) | Planned: CI/CD and Docker Hub publishing (priority 1) |
| [phases/phase-8-security-guardrails.md](phases/phase-8-security-guardrails.md) | Planned: LLM Guard prompt-injection and PII guardrails (priority 2) |
| [phases/phase-9-orchestration.md](phases/phase-9-orchestration.md) | Planned: Prefect orchestration for ingestion (priority 3) |
| [phases/phase-10-agentic-tracing.md](phases/phase-10-agentic-tracing.md) | Planned: Opik agentic/LLM-call tracing (priority 4) |
| [phases/phase-11-evaluation.md](phases/phase-11-evaluation.md) | Planned: RAGAS evaluation harness (priority 5) |

## Assets

Screenshots and exported diagrams live in [images](images). Reference them from any document with a
relative path, for example:

```markdown
![RAG overview dashboard](images/grafana-rag-overview.png)
```
