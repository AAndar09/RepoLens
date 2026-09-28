# Architecture

## Phase 9 system context

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

The investigation model builds planning, sufficiency, and synthesis prompts above a common provider
contract:

```text
LangGraph -> provider factory -> Gemini (primary)
                              -> Groq (one bounded fallback)
                              -> OpenRouter (optional)
                              -> Ollama (optional/local)
```

Gemini uses its native REST API; Groq and OpenRouter share an isolated OpenAI-compatible adapter;
Ollama uses its local chat API. Groq uses JSON-object mode for RepoLens's flexible tool-argument
schemas; every provider's structured result is authoritatively validated with Pydantic. Provider/model,
latency, outcome, fallback use, and available token counts are logged and returned in the developer
trace. Planning can select only `search_code`, `lookup_symbol`, `read_source`,
`structural_lookup`, and `repository_metadata`. These wrappers reuse hybrid retrieval and structural
graph services and carry snapshot context internally; the model never receives shell, filesystem,
database, Qdrant, or infrastructure credentials.

Every tool call produces a success/error trace. Source evidence receives a stable ID and immutable
commit URL. Synthesis may cite only returned citable evidence IDs. The workflow enforces configured
limits for investigation rounds, calls per round, evidence items, source lines, and evaluation
evidence context. Model calls retain evidence IDs and citations but use bounded previews of
oversized tool data and citation excerpts, keeping provider requests within model/context limits. An independent
LangGraph recursion limit also applies. A tool failure does not terminate other calls.

## Deterministic query routing

Before a routed query reaches retrieval or the investigation agent, a deterministic classifier maps clear lexical signals to existing controlled capabilities: direct metadata, direct symbol lookup, hybrid retrieval, or the bounded LangGraph investigation. It does not load a model or access source files, tools, infrastructure, or credentials.

The response and application log include category, route, confidence, and fallback status. Questions with no unambiguous deterministic match use full investigation. The labelled evaluation dataset measures category and route accuracy.

## Evaluation

`app/evaluation` loads strictly validated, versioned JSON datasets tied to full Git commit SHAs and
resolves only matching ready snapshots. The CLI calls the production retriever, deterministic
router, and controlled symbol lookup tool. It never substitutes live branch state. Reports retain
the dataset content hash, retrieval/embedding configuration, raw ranked evidence, deterministic
metrics, comparison deltas, and latency summaries.

Semantic-only and hybrid retrieval are directly comparable. Structural graph lookup remains a
separate agent tool, and no production reranker exists, so both hybrid-plus-structural ranking and
reranked experiments are reported as unsupported rather than simulated. Model-assisted metrics
have a separate report section and are disabled by default.

## Dependency and vulnerability intelligence

Ingestion independently detects bounded `requirements*.txt` files and PEP 621 dependency tables in `pyproject.toml`. Valid PEP 508 declarations are snapshot-scoped with manifest path, line, scope, marker, declared constraint, normalized PyPI name, and an exact version only when deterministically pinned. Open constraints remain visible but are not treated as installed versions.

The dedicated OSV integration queries exact package versions and persists both normalized findings and raw source records. A successful empty response is cached using the dependency check timestamp; refresh failures retain previous findings and expose the error. Inventory, scan, and finding APIs are separate from the LLM. Controlled dependency and vulnerability tools let the agent combine these external facts with source retrieval while its prompt explicitly prohibits equating a match with exploitability.

## Boundaries and configuration

- `app/api`: versioned HTTP contract.
- `app/services`: Git acquisition and ingestion orchestration.
- `app/analysis`: deterministic Python AST analysis.
- `app/retrieval`: units, embeddings, lexical/hybrid strategy, and Qdrant adapter.
- `app/graph`: deterministic import resolution and bounded structural traversal.
- `app/agent`: model abstraction, controlled tools, and LangGraph investigation workflow.
- `app/routing`: deterministic route policy, direct controlled execution, and evaluation dataset.
- `app/evaluation`: dataset contracts, deterministic metrics, benchmark runner, and JSON export.
- `app/dependencies`: manifest extraction, OSV integration, and persisted vulnerability service.
- `app/models` and `migrations`: relational schema authority.
- `frontend/src/App.tsx`: snapshot-scoped public workspace and capability views.
- `frontend/src/api.ts`: typed browser contract for the versioned backend API.

## Public frontend

The static React/Vite application leads users through repository submission, synchronous ingestion, and retrieval indexing before opening a snapshot workspace. The current repository, branch, and immutable commit remain visible across overview, investigation, source exploration, structural graph, dependency, and security views. AI explanations are visually separated from commit-pinned evidence and optional tool traces.

Only repository/snapshot identifiers are retained in browser local storage for refresh recovery. Source, findings, and AI responses are reloaded from the backend and are not persisted by the frontend. Independent workspace requests are failure-isolated so an unavailable retrieval or graph service does not hide otherwise usable snapshot intelligence.

The existing developer trace shows non-secret provider/model, duration, fallback, and token metadata
for generative calls. Provider selection remains server-controlled.

All runtime settings use `REPOLENS_`. `.env.example` documents ingestion and retrieval limits,
agent safeguards, provider/model selection, and backend-only credentials. Credentials are validated
only when their provider is invoked, so unused integrations do not affect startup. Compose connects
the backend to Qdrant and permits optional host Ollama access through `host.docker.internal`.
Generative inference never replaces the independent local embedding path.

Generative settings are `REPOLENS_LLM_PROVIDER`, `REPOLENS_LLM_MODEL`,
`REPOLENS_LLM_FALLBACK_PROVIDER`, `REPOLENS_LLM_FALLBACK_MODEL`, and
`REPOLENS_LLM_TIMEOUT_SECONDS`. Backend-only credentials are
`REPOLENS_GEMINI_API_KEY`, `REPOLENS_GROQ_API_KEY`, and
`REPOLENS_OPENROUTER_API_KEY`. Each cloud integration has a configurable `*_BASE_URL`;
OpenRouter additionally accepts an optional site URL, and Ollama uses `REPOLENS_OLLAMA_URL`.
Neither keys nor provider selection are exposed through Vite settings or browser responses.

Background jobs, private repositories, non-Python manifests, dependency resolution/lockfile solving, reachability analysis, conversation memory, and unrestricted agent tools remain out of scope.
