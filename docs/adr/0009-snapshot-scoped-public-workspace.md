# ADR 0009: Present RepoLens as a snapshot-scoped public workspace

## Status

Accepted

## Context

The backend exposes repository ingestion, retrieval, structural, dependency, vulnerability, and investigation capabilities through snapshot-scoped APIs. The public frontend needs to make these usable without implying conversation history, background processing, authentication, or analysis capabilities that do not exist.

## Decision

Use one React workspace with explicit views for overview, questions, files/symbols, structure, dependencies, and security. Keep the selected repository and immutable snapshot visible in the workspace header. Automatically create the retrieval index after ingestion because Ask RepoLens depends on it, while loading independent deterministic views even if one service fails.

Persist only the selected repository and snapshot identifiers in browser local storage so a refresh can restore the workspace through existing GET APIs. Do not persist AI answers or repository source in the browser. Keep developer tool traces collapsed behind an optional disclosure, and present explanations separately from commit-pinned evidence.

## Consequences

The main workflow requires no API console. Static deployment remains possible because navigation is client state rather than server routes. A user can restore the last local workspace but cannot browse all previously submitted repositories because the backend has no repository-list endpoint. Ingestion and investigations remain synchronous, so the UI can communicate progress but cannot resume an interrupted request.
