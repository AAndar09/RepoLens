# Architecture

## Phase 5 system context

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

## Structural graph

The relational source model is also the graph model: source files are module nodes, symbols are
nodes contained by their `source_file_id`, and `parent_id` is the AST-derived symbol-containment
edge. This avoids copying facts already enforced by foreign keys. One persisted
`module_import_resolutions` row records the outcome for every parsed import in a snapshot.

Import resolution is conservative. Absolute module names and Python relative-import levels are
resolved only against uniquely matching indexed modules. Configured source roots (default `src`)
provide deterministic aliases for common source layouts. A match is `resolved`; multiple physical
matches are `ambiguous`; and no indexed match or an invalid relative traversal is `unresolved`.
Each record retains the requested module, candidate paths, and a reason. No call graph or dynamic
import behavior is inferred.

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

## Investigation agent

The first investigation workflow is a compiled LangGraph state graph:

```text
plan -> execute controlled tools -> evaluate evidence --insufficient--> execute tools
                                      |
                                      +--sufficient/terminated--> synthesize
```

The model provider is abstracted behind planning, sufficiency, and synthesis contracts. The default
adapter calls a host Ollama instance and requires JSON-schema-constrained responses validated with
Pydantic. Planning can select only `search_code`, `lookup_symbol`, `read_source`,
`structural_lookup`, and `repository_metadata`. These wrappers reuse hybrid retrieval and structural
graph services and carry snapshot context internally; the model never receives shell, filesystem,
database, Qdrant, or infrastructure credentials.

Every tool call produces a success/error trace. Source evidence receives a stable ID and immutable
commit URL. Synthesis may cite only returned citable evidence IDs. The workflow enforces configured
limits for investigation rounds, calls per round, evidence items, and source lines, plus an
independent LangGraph recursion limit. A tool failure does not terminate other calls.

## Boundaries and configuration

- `app/api`: versioned HTTP contract.
- `app/services`: Git acquisition and ingestion orchestration.
- `app/analysis`: deterministic Python AST analysis.
- `app/retrieval`: units, embeddings, lexical/hybrid strategy, and Qdrant adapter.
- `app/graph`: deterministic import resolution and bounded structural traversal.
- `app/agent`: model abstraction, controlled tools, and LangGraph investigation workflow.
- `app/models` and `migrations`: relational schema authority.

All runtime settings use `REPOLENS_`. `.env.example` documents ingestion and retrieval limits,
structural source roots, agent safeguards, and Ollama configuration. Compose connects the backend
to Qdrant and permits access to a host Ollama instance through `host.docker.internal`.

Background jobs, private repositories, non-Python code, conversation memory, Laya routing,
vulnerability analysis, and unrestricted agent tools remain out of scope.
