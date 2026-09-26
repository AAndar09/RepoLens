# RepoLens

RepoLens ingests public GitHub Python repositories, records immutable commit snapshots, and offers
lexical, semantic, hybrid, and deterministic structural code retrieval with commit-pinned source
evidence.

## Quick start

Prerequisite: Docker Desktop with Compose running.

```bash
cp .env.example .env
docker compose up --build
```

Open the [frontend](http://localhost:5173), [API docs](http://localhost:8000/docs), or
[Qdrant dashboard](http://localhost:6333/dashboard). Submit and ingest a small repository such as
`https://github.com/pypa/sampleproject`, then build its retrieval index through the API.

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
