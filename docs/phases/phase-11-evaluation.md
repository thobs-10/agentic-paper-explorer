# Phase 11 - RAG evaluation harness (planned, priority 5)

`project.md` already commits to RAGAS for evaluation, and `src/agentic_paper_explorer/evaluation`
exists as an empty package waiting for this phase.

## Why priority 5 (last)

Evaluation is most useful once there is traced, guarded, orchestrated traffic to evaluate against -
it depends on Phase 8 (clean, non-injected inputs), Phase 9 (repeatable ingestion so the corpus is
stable), and Phase 10 (Opik traces as a source of real query/answer/context triples). Running an
evaluation harness before those exist would mean evaluating against ad hoc, unguarded, untraced
data.

## Tool choice

**RAGAS** (open source, already decided in `project.md`), scored against reference-free metrics that
do not require hand-labeled ground truth, since the corpus is arbitrary arXiv search results rather
than a fixed benchmark set.

| Metric | What it checks | Inputs it needs |
| --- | --- | --- |
| `Faithfulness` | Answer claims are supported by retrieved chunks | query, answer, contexts |
| `AnswerRelevancy` | Answer actually addresses the query | query, answer |
| `ContextPrecision` | Retrieved chunks are relevant, not noise | query, contexts |
| `ContextRecall` | Retrieval did not miss relevant material (needs a reference answer) | query, contexts, reference |

Start with the first three (no ground truth needed) and add `ContextRecall` once a small
hand-curated question set exists.

## What to build

| Concern | Location |
| --- | --- |
| Evaluation dataset builder | `src/agentic_paper_explorer/evaluation/dataset.py` (new) - pulls query/answer/context triples either from Opik traces (Phase 10) or from a fixture file for offline runs |
| RAGAS scoring runner | `src/agentic_paper_explorer/evaluation/runner.py` (new) - calls the backend's own generation service (or the live API) and scores the result with RAGAS |
| Evaluation config | `src/agentic_paper_explorer/evaluation/configs/` (already exists, currently only `.gitkeep`) - thresholds per metric, model used for RAGAS's own judge calls (route through LiteLLM, not a separate provider key) |
| CLI entry point | `evaluation/runner.py` `__main__`, so it can run in CI as a scheduled job, not a blocking PR check |
| CI integration | `.github/workflows/evaluation.yml` (new, separate from `ci.yml`) - scheduled (for example nightly) run against a fixed question set, publishing a score summary as a workflow artifact |
| Tests | `tests/evaluation/test_dataset.py`, `tests/evaluation/test_runner.py` - mock RAGAS's LLM judge calls, following the existing "mock every external API and model provider" rule |

## Design approach

- RAGAS needs an LLM to judge faithfulness/relevancy - route that judge call through the existing
  LiteLLM gateway (`generation/provider.py`) rather than adding a second model-access path, keeping
  with "prefer lightweight open-source or small language models as default."
- Keep this as a scheduled/manual job, not a per-PR gate - RAGAS scoring is slower and costs model
  calls, which does not belong in the fast feedback loop Phase 7's CI provides.
- Store historical scores as workflow artifacts first; only add a persistence layer (a Qdrant
  collection or a small table) if trend tracking over time becomes a real need.

## Concrete steps

1. Add `ragas` to a new `evaluation` optional-dependency group in `pyproject.toml`.
2. Build a small fixture set of representative questions (reuse the queries already used for manual
   testing, for example "What are transformer models used for in NLP?").
3. Implement `runner.py` to call the backend's generation path for each fixture question, collect
   the RAGAS inputs, score them, and print/export a summary table.
4. Add the scheduled GitHub Actions workflow once the runner works locally against a running stack.
5. Document baseline scores in `docs/phases/phase-11-evaluation.md` follow-up notes (or a dedicated
   results doc) once the first real run completes.
