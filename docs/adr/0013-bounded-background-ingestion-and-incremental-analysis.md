# ADR 0013: Bounded background ingestion and incremental analysis

## Status

Accepted

## Context

Repository cloning, AST extraction, graph construction, and retrieval indexing can outlive a normal
HTTP request. The synchronous Phase 2 endpoint also gave operators no durable record of queued or
interrupted work. Re-indexing a new commit reparsed every Python file even when most file content
was unchanged.

## Decision

The public frontend uses database-backed `ingestion_jobs`. FastAPI schedules each job after the
response, while an in-process bounded semaphore limits concurrent ingestion. Job status, attempts,
errors, timestamps, repository, and resulting snapshot are durable. On process startup, queued or
running jobs are marked failed with an explicitly retryable error; a new POST safely creates a new
attempt. The old synchronous endpoint remains deprecated for compatibility.

For a new commit, ingestion compares each accepted path and SHA-256 hash with the most recent ready
snapshot. Unchanged files copy deterministic AST intelligence into the new immutable snapshot;
changed and new files are parsed; absent paths are omitted and counted as removed. The structural
graph is rebuilt from the new snapshot. Retrieval units and vectors are rebuilt because their
identity and index lifecycle are snapshot-scoped.

The production container runs one API process. The in-process dispatcher is intentionally not
presented as a distributed queue.

## Consequences

- Browser requests return a pollable job immediately and can report failure clearly.
- Restarted work is diagnosable and retryable instead of remaining permanently `running`.
- AST work is proportional to changed Python files for normal subsequent commits.
- Multiple API replicas would need an external queue/lease mechanism before ingestion can be
  dispatched safely across replicas.
- Vector rebuilding remains a known optimization opportunity.
