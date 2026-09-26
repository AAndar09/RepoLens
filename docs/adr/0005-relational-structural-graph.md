# ADR 0005: Represent the structural graph with relational facts

## Status

Accepted

## Context

RepoLens already persists snapshot-scoped files, AST symbols, symbol parents, and import statements.
Phase 4 needs deterministic traversal and transparent import resolution without overstating static
analysis coverage.

## Decision

Treat source files and symbols as graph nodes and their existing foreign keys as containment edges.
Persist one resolution outcome per source import, scoped explicitly to its snapshot. Resolve only
unique indexed module matches, recording ambiguous candidates and unresolved reasons otherwise.
Expose bounded application services and HTTP routes for module symbols/importers/imports and symbol
containment. Do not add a graph database or derive call edges.

## Consequences

Graph facts remain normalized, transactional with ingestion, and portable across SQLite and
PostgreSQL. Existing snapshots require an idempotent graph rebuild to populate import resolutions.
Dynamic imports, runtime path manipulation, re-exports, and calls remain intentionally unknown.
