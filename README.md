# RepoLens

RepoLens ingests public GitHub Python repositories, records immutable commit snapshots, and offers
lexical, semantic, hybrid, and deterministic structural code retrieval with commit-pinned source
evidence. It also extracts Python dependency manifests and can cache version-specific public OSV
vulnerability findings.

## Quick start

Prerequisite: Docker Desktop with Compose running.

```bash
cp .env.example .env
docker compose up --build
```

Open the [frontend](http://localhost:5173), [API docs](http://localhost:8000/docs), or
[Qdrant dashboard](http://localhost:6333/dashboard). Submit and ingest a small repository such as
`https://github.com/pypa/sampleproject`. The frontend ingests it, builds its retrieval index, and
opens the repository workspace without requiring the API console.

Investigations use configurable backend-only generative inference. The intended demo deployment
uses Gemini with Groq as a bounded availability fallback. Add `REPOLENS_GEMINI_API_KEY` to `.env`;
add `REPOLENS_GROQ_API_KEY` only if fallback should be usable. OpenRouter and Ollama remain optional.
No provider credential is sent to the browser, and missing credentials for unused providers do not
prevent the application from starting.

To use Ollama locally instead, set `REPOLENS_LLM_PROVIDER=ollama`, set
`REPOLENS_LLM_MODEL=qwen2.5-coder:7b`, and pull that model on the host. Embeddings remain local and
independent of the generative provider in every configuration.
The workspace exposes source/symbol exploration, structural imports, dependency inventory, OSV
findings, deterministically routed repository questions, commit-pinned evidence, and optional tool
traces. Ambiguous questions use the bounded cloud investigation workflow.

Stop with `docker compose down`. Use `--volumes` only to intentionally erase local PostgreSQL and
Qdrant data.

## Generative provider configuration

`REPOLENS_LLM_PROVIDER` and `REPOLENS_LLM_MODEL` select the primary. The optional
`REPOLENS_LLM_FALLBACK_PROVIDER` and `REPOLENS_LLM_FALLBACK_MODEL` select one availability
fallback; set both empty to disable it. `REPOLENS_LLM_TIMEOUT_SECONDS` applies to each provider
attempt.

Provider credentials are `REPOLENS_GEMINI_API_KEY`, `REPOLENS_GROQ_API_KEY`, and
`REPOLENS_OPENROUTER_API_KEY`. Optional endpoint settings are documented in `.env.example`, along
with `REPOLENS_OPENROUTER_SITE_URL` and `REPOLENS_OLLAMA_URL`. Keys are read only by the backend.
The checked-in Gemini example uses `gemini-3.5-flash-lite`, which keeps the multi-stage investigation
workflow responsive and reduces fallback-provider pressure. Model IDs remain entirely configurable.

From `backend`, smoke-test one configured provider manually (never run by CI):

```bash
python scripts/provider_smoke.py --provider gemini --model gemini-3.5-flash-lite
python scripts/provider_smoke.py --provider groq --model openai/gpt-oss-20b
python scripts/provider_smoke.py --provider openrouter --model openai/gpt-oss-20b
python scripts/provider_smoke.py --provider ollama --model qwen2.5-coder:7b
```

## Validation

```bash
cd backend
ruff check .
pytest -q

cd ../frontend
npm run lint
npm test
npm run build
```

## Evaluation

Versioned, commit-pinned benchmark datasets and the deterministic evaluation CLI live under
`backend/evaluations`. After ingesting and indexing the exact dataset snapshot, compare semantic
and hybrid retrieval with:

```bash
docker compose exec backend python -m app.evaluation.cli \
  evaluations/datasets/v1/sampleproject.json \
  --configuration semantic --configuration hybrid \
  --output evaluations/results/sampleproject.json
```

Reports include raw ranked evidence, Recall@K, citation metadata correctness, symbol/routing/direct
tool-selection accuracy, latency, and configuration deltas. See [evaluation documentation](docs/evaluation.md)
for metric definitions and reproducibility constraints.

See [architecture](docs/architecture.md), [API](docs/API.md), and [ADRs](docs/adr).
