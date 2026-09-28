# Evaluation framework

RepoLens evaluation datasets are versioned JSON files under
`backend/evaluations/datasets/<schema-version>/`. Every repository entry uses a normalized public
GitHub URL and a full 40-character commit SHA. The runner will not substitute a newer branch head:
the exact snapshot must already be ready and retrieval-indexed in RepoLens.

The initial dataset, `sampleproject.python.v1`, targets PyPA sampleproject commit
`621e4974ca25ce531773def586ba3ed8e736b3fc`. Its labels cover retrieval targets, exact symbol
lookup, deterministic routing, and directly measurable tool selection. Dataset changes require a
new dataset ID or schema-version directory rather than silently changing the meaning of an old
result.

## Running a benchmark

Start RepoLens and submit/ingest the dataset repository through the normal UI or API. Confirm that
the indexed commit equals the dataset commit; then create the retrieval index. From the repository
root run:

```bash
docker compose exec backend python -m app.evaluation.cli \
  evaluations/datasets/v1/sampleproject.json \
  --configuration semantic \
  --configuration hybrid \
  -k 1 -k 3 -k 5 \
  --output evaluations/results/sampleproject.json
```

The installed backend also exposes the equivalent `repolens-evaluate` console command. Omit
`--output` to print JSON. A missing exact snapshot or retrieval index fails the run instead of
silently ingesting mutable branch state.

Each report contains the dataset SHA-256, snapshot IDs, embedding provider/dimensions, retrieval
configurations, K values, raw ranked evidence, per-case scores, aggregate scores, comparison
deltas, and latency distribution. Keep the dataset and exported JSON together when comparing
runs. Latency is machine/load dependent even when ranking metrics are reproducible.

## Dataset case fields

- `repository` and `commit` identify one immutable public snapshot.
- `question` and `question_type` describe the benchmark input.
- `expected_files` and `expected_symbols` label relevant retrieval targets.
- `symbol_query` enables exact symbol-lookup measurement.
- `expected_routing` labels category and strategy.
- `expected_tools` lists acceptable tools for directly measurable routes.
- `retrieval: false` marks routing/metadata cases that have no retrieval relevance labels.

Datasets are strictly validated: unknown fields, abbreviated SHAs, unsafe paths, duplicate labels,
and retrieval cases without relevance targets are rejected.

## Deterministic metrics

- **Retrieval Recall@K** uses the union of labelled file and symbol targets. A retrieved unit may
  satisfy both targets.
- **Citation correctness@K** is the fraction of returned evidence units that are both relevant to
  a labelled file/symbol and traceable to a valid line range in the indexed snapshot. Source URLs
  in raw results are pinned to the dataset commit. This is evidence/citation metadata correctness,
  not an LLM judgement that prose is supported.
- **Symbol lookup accuracy** is a binary per-case exact-name/qualified-name check through the
  production controlled symbol tool.
- **Routing accuracy** measures exact category and strategy matches.
- **Tool-selection accuracy** measures direct deterministic routes only. Cases requiring the full
  investigation agent are reported as unmeasured rather than counted as failures or successes.
- **Latency** records wall-clock retrieval, routing, and symbol lookup time with mean, median, and
  p95 summaries.

The default experiment compares semantic-only with hybrid retrieval end to end. Lexical-only is
also available. The report explicitly marks hybrid-plus-structural and reranked configurations as
unsupported because the current production retriever does not implement those ranking stages.

Model-assisted answer-quality or groundedness grading is disabled in this phase and is represented
in the report separately from deterministic metrics. Future model judges must record judge
provider/model/prompt version and must never be blended into deterministic scores.

No benchmark numbers are checked into documentation unless they come from an exported run.

## Frontend reporting

The backend reads valid bounded reports from `REPOLENS_EVALUATION_RESULTS_DIR` and exposes summary
metrics at `GET /api/v1/evaluations/results`. The frontend **Evaluations** view presents retrieval
configurations, deterministic accuracy/latency, comparisons, and whether model-assisted grading was
enabled. It never calculates or substitutes missing scores in the browser. Refresh the application
after writing a new report; reports are operational artifacts and the API is read-only.
