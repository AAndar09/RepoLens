# Architecture

## Phase 3 system context

RepoLens is a React application backed by FastAPI. PostgreSQL is the durable authority for
repositories, immutable snapshots, extracted Python intelligence, retrieval units, and index
lifecycle. Qdrant holds only vectors and is always queried with a snapshot payload filter.

```text
Browser -> React/Vite (:5173) -> FastAPI /api/v1 (:8000) -> PostgreSQL (:5432)
                                             |                  |
                                             +-- safe Git clone  +-- Qdrant (:6333)
                                             +-- AST extraction  +-- hybrid retrieval
```

## Ingestion and data model

Ingestion shallow-clones a public repository with Git prompts, hooks, global/system config, and
LFS smudging disabled. It records default branch and full commit SHA, applies configured source
limits, hashes/decodes accepted Python files, and uses `ast` to persist modules, classes,
functions, methods, imports, and source ranges. Repository code is never executed.

`repositories` identifies GitHub repositories. `repository_snapshots` is unique by repository and
commit. `source_files`, `code_symbols`, and `source_imports` are snapshot-scoped intelligence.
`snapshot_retrieval_indexes` records one retrieval lifecycle per snapshot, while `retrieval_units`
retain bounded symbol-aware chunks, source metadata, and materialized lexical text.

## Retrieval

Indexing normally produces one unit per extracted symbol, including module symbols. Oversized
symbols are divided on line boundaries when possible. The default configurable `hashing` embedding
provider is local and deterministic (384 dimensions); the provider interface permits future
replacement without changing callers. Qdrant vectors include snapshot, path, symbol kind, and
language payload metadata.

Lexical search ranks query tokens against persisted code-aware fields. Semantic search queries
Qdrant, then resolves hits through relational units in the selected retrieval index. Hybrid search
uses reciprocal-rank fusion. This dual relational/vector scope prevents evidence crossing snapshot
boundaries. Evidence has path, precise stored line range, symbol metadata, component scores, and a
GitHub link pinned to the immutable indexed commit.

## Boundaries and configuration

- `app/api`: versioned HTTP contract.
- `app/services`: Git acquisition and ingestion orchestration.
- `app/analysis`: deterministic Python AST analysis.
- `app/retrieval`: units, embeddings, lexical/hybrid strategy, and Qdrant adapter.
- `app/models` and `migrations`: relational schema authority.

All runtime settings use `REPOLENS_`. `.env.example` documents ingestion limits, Qdrant endpoint,
embedding provider/dimensions, and retrieval limits. The Compose backend points at `qdrant:6333`;
native development defaults to `localhost:6333`.

Background jobs, private repositories, non-Python code, learned/remote embedding providers,
vulnerability analysis, LangGraph/Laya, and autonomous agents remain out of scope.
