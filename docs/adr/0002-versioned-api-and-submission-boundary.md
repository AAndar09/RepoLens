# ADR 0002: Versioned API and repository submission boundary

- Status: Accepted
- Date: 2026-09-26

## Context

The foundation needs a stable frontend/backend contract and an initial representation of a public GitHub repository, while ingestion and analysis are explicitly out of scope.

## Decision

Expose HTTP routes under `/api/v1`. Treat a repository submission as a canonical GitHub URL plus extracted owner/name and a single `submitted` status. Enforce uniqueness on owner/name in the database and return `409` for repeat submissions.

Only syntactic public-GitHub validation occurs at this boundary. No GitHub network request, clone, snapshot, branch, or commit is resolved in Phase 1.

## Consequences

- The client has a durable identifier it can use in later phases.
- Snapshot fields will require a later migration once ingestion is in scope.
- A URL may be syntactically valid but refer to a missing or non-public repository; that distinction is intentionally deferred.

