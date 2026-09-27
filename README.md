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

Investigations use a local Ollama model by default. Install Ollama on the host and run
`ollama pull qwen2.5-coder:7b`, then call the snapshot investigation endpoint in the API docs.
The workspace exposes source/symbol exploration, structural imports, dependency inventory, OSV
findings, routed repository questions, commit-pinned evidence, and optional tool traces. Laya is
installed with the backend and lazily downloads/loads its local routing model on the first query.

Stop with `docker compose down`. Use `--volumes` only to intentionally erase local PostgreSQL and
Qdrant data.

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

See [architecture](docs/architecture.md), [API](docs/API.md), and [ADRs](docs/adr).
