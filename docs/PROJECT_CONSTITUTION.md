# RepoLens AI — Project Constitution

## Product

RepoLens is a public, agentic code-intelligence platform for public GitHub repositories.

A user provides the URL of a public repository. RepoLens ingests and analyses a specific repository snapshot, builds semantic and structural representations of the source code, and allows users to investigate the codebase through an AI assistant.

The assistant should be able to answer architecture, implementation, dependency, documentation, maintenance and security questions using evidence from the indexed repository.

Code-related answers should provide file and line-level citations wherever possible.

## Primary portfolio objectives

The project exists both as a useful application and as a demonstration of AI engineering competence.

It should visibly demonstrate:

- retrieval-augmented generation
- hybrid retrieval
- embeddings
- reranking
- agent orchestration
- tool use
- structured outputs
- lightweight AI decision routing with Laya
- AST-based code understanding
- graph/structural retrieval
- external API integration
- evaluation
- observability
- FastAPI backend engineering
- React frontend engineering
- SQL persistence
- vector databases
- Docker
- automated testing
- CI/CD
- production-minded failure handling

## Initial scope

The first supported source is a public GitHub repository.

The initial supported programming language is Python.

The system must not require GitHub authentication for normal public-repository use.

Private repository support, user accounts and repository write operations are out of scope until explicitly added later.

## Core architectural principle

Prefer deterministic software whenever a task can be solved reliably without an LLM.

Use:

- deterministic parsing for source-code structure
- AST processing for symbols and imports
- deterministic graph traversal for known relationships
- deterministic line calculation and citations
- normal APIs for external data
- search algorithms for retrieval

Use Laya for lightweight classification and routing decisions.

Use a generative LLM for ambiguous interpretation, investigation planning and synthesis.

## Snapshot integrity

Repository intelligence must be associated with a specific repository snapshot identified by branch and commit SHA.

Citations should reference the indexed commit rather than an unstable branch such as `main` whenever possible.

## Retrieval model

The target retrieval architecture combines:

- semantic/vector retrieval
- lexical retrieval
- symbol lookup
- structural/graph retrieval
- metadata filtering

The agent should be able to combine these rather than relying exclusively on embeddings.

## Agent architecture

LangGraph is the preferred orchestration layer.

The agent should use controlled application tools rather than unrestricted shell or infrastructure access.

Typical tools may include:

- search_code
- search_docs
- lookup_symbol
- read_source
- find_importers
- find_dependencies
- find_tests
- query_repository_metadata
- get_recent_commits
- query_github
- check_vulnerability

Tool names and implementations may evolve.

## Decision layer

Laya should have a narrow, defensible role.

Appropriate uses include:

- classifying user questions
- routing queries
- selecting retrieval strategies
- deciding whether deeper reasoning is needed

Do not use Laya simply to claim that the project contains an additional AI technology.

## Models

Development should support local models where practical, for example through Ollama.

Model access must be abstracted so a different local or hosted model can be configured later without major application redesign.

## Persistence

Use relational persistence for application/domain data.

Use Qdrant for vector search unless an Architecture Decision Record explicitly changes this choice.

The development environment may use SQLite where appropriate, but PostgreSQL is the intended production relational database.

## Frontend

The target frontend is React with Vite.

The frontend must communicate with the backend through documented APIs and must be buildable as static HTML/CSS/JavaScript assets suitable for normal web hosting.

## Security

The initial application supports public repositories only.

Do not implement private repository tokens, repository mutation or arbitrary code execution unless explicitly scoped in a future phase.

Repository input must be validated and resource limits must exist to prevent unbounded ingestion.

## Evaluation

AI quality must eventually be measured rather than assessed only through demos.

The project should support benchmarks for:

- retrieval recall
- citation correctness
- tool-selection accuracy
- groundedness
- latency

Evaluation results must come from actual experiments rather than invented numbers.

## Development philosophy

Work phase-by-phase.

Before changing code:

1. inspect the current repository;
2. read relevant documentation and ADRs;
3. identify existing patterns;
4. preserve working interfaces unless there is a reason to change them.

Do not assume that earlier phases were implemented using particular filenames, classes or internal structures.

The current repository is the implementation source of truth.

If an architectural change is justified:

1. implement it cleanly;
2. update affected tests;
3. update relevant documentation;
4. create or update an ADR when the decision is significant.

Prefer cohesive incremental changes over large rewrites.

Do not implement future phases prematurely unless a small abstraction is necessary to avoid obvious technical debt.

## Quality expectations

At the end of each phase:

- relevant tests must pass;
- new behaviour should have tests;
- type checking/linting should remain healthy where configured;
- documentation must reflect meaningful changes;
- no secrets should be committed;
- `.env.example` should remain accurate;
- the application should remain runnable according to the documented development workflow.