# Operations

## Diagnosis and recovery

Every API response carries `X-Request-ID`; JSON logs include that ID, route, status, and latency.
Routing, LLM provider attempts, controlled agent tool calls, and ingestion job outcomes are emitted
as structured events without prompts, source content, or credentials. Job status and its bounded
error message are available from the ingestion-job API.

Queued/running jobs found during startup are marked failed because v1 cannot prove their worker is
still alive. Resubmit ingestion to retry. Snapshot creation is commit-idempotent, and retrieval
index replacement is snapshot-scoped, so retrying does not create duplicate source intelligence.

## Data and backups

PostgreSQL is authoritative for repositories, snapshots, source intelligence, dependencies,
findings, retrieval units, evaluation metadata references, and jobs. Use normal PostgreSQL physical
or logical backups and regularly test restoration. Back up encryption keys and provider secrets in
the deployment secret manager, not with source code.

Qdrant stores derived vectors. Its volume can be snapshotted for faster recovery, but it can also be
reconstructed by rebuilding retrieval indexes from PostgreSQL. Restore PostgreSQL first and never
mix Qdrant data from a different relational backup without re-indexing.

No automatic snapshot retention policy exists in v1. Operators must monitor PostgreSQL/Qdrant disk
usage and define retention appropriate to their deployment before opening the service broadly.

## Monitoring

Alert on readiness failures, HTTP 5xx/429 rates, ingestion job failures and age, provider failure or
fallback rate, query latency, database capacity, Qdrant capacity, and `/tmp` exhaustion. Evaluation
reports are generated offline by the versioned CLI and exposed read-only to the frontend.
