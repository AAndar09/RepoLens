# Architecture

## Phase 2 system context

RepoLens is a React single-page application backed by a versioned FastAPI API. The API owns repository validation, bounded Git acquisition, deterministic Python analysis, and relational persistence. PostgreSQL is the normal Docker Compose database; SQLite remains available for lightweight native development and tests. Alembic is the schema authority.

Qdrant is provisioned for later retrieval phases but Phase 2 does not create collections or connect application code to it.

```text
Browser
  | HTTP/JSON
  v
React/Vite (:5173) ---> FastAPI /api/v1 (:8000) ---> PostgreSQL (:5432)
                              |
                              +-- shallow HTTPS clone --> temporary checkout
                              |                            (deleted after use)
                              +-- Python ast parsing
                              |
                              +-- future retrieval ------> Qdrant (:6333/:6334)
```

## Ingestion sequence

1. A canonical `https://github.com/{owner}/{repository}` URL is submitted.
2. An explicit ingestion request marks the repository `ingesting`.
3. Git makes a shallow, non-recursive HTTPS clone in a temporary directory with prompts, hooks, global/system Git configuration, and LFS smudging disabled.
4. RepoLens records the checked-out branch and full commit SHA.
5. The walker applies configured file globs, excluded directories, and file/count/byte limits.
6. Accepted Python files are decoded using Python's declared-source-encoding rules and hashed with SHA-256.
7. Python's standard `ast` module extracts modules, classes, functions, methods, and imports with line ranges.
8. The snapshot and its intelligence are committed, and the temporary checkout is deleted.

Repository code is read but never imported or executed. Symlinks, binary files, unsupported files, and individually oversized files are skipped. A repository that exceeds aggregate limits fails the ingestion rather than storing partial intelligence. Syntax-invalid Python is retained with a `malformed` status and diagnostic so one bad file does not fail the snapshot.

## Relational model

- `repositories`: canonical GitHub identity and latest ingestion status/error.
- `repository_snapshots`: immutable repository commit identity, branch, ingestion status, and aggregate counts.
- `source_files`: snapshot-scoped path, module name, source text, SHA-256, size, line count, and parse outcome.
- `code_symbols`: hierarchical module/class/function/method records with exact available AST line ranges.
- `source_imports`: normalized `import` and `from ... import ...` records with aliases, relative level, and line ranges.

A `(repository_id, commit_sha)` uniqueness constraint makes repeat ingestion idempotent. Re-ingesting an already completed commit returns its existing snapshot. A failed snapshot may be retried and rebuilt.

## Backend boundaries

- `app/api`: versioned HTTP transport and bounded query endpoints.
- `app/schemas`: request and response contracts.
- `app/models`: SQLAlchemy persistence models and enums.
- `app/services/acquisition.py`: safe Git process boundary and checkout metadata.
- `app/services/ingestion.py`: file policy, limits, hashing, and persistence orchestration.
- `app/analysis/python_ast.py`: deterministic Python AST extraction.
- `app/config.py`: typed environment configuration.
- `migrations`: explicit and reversible schema history.

Ingestion currently runs synchronously in FastAPI's worker thread. This keeps Phase 2 operationally small and makes status durable, but deployments should use conservative limits and timeouts. A later workload-driven ADR may introduce a job queue without changing the snapshot model.

## Configuration and limits

All settings use the `REPOLENS_` prefix. `.env.example` documents include/exclude policy, clone timeout, clone-size, candidate-file count, total source bytes, and per-file bytes. Production deployments must also replace the example database password and restrict browser origins.

## Deferred concerns

Background workers, explicit branch selection, authenticated/private repositories, non-Python languages, lexical indexing, embeddings, Qdrant collections, retrieval, model providers, LangGraph, Laya, OSV, and autonomous tools remain out of scope.

