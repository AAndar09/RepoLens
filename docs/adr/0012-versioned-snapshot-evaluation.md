# ADR 0012: Evaluate production interfaces against versioned immutable snapshots

## Status

Accepted

## Context

RepoLens had unit tests and a small in-code routing label set, but no reproducible way to compare
retrieval configurations or export auditable quality metrics. Evaluating a moving branch would make
labels and results incomparable. Reimplementing retrieval inside a benchmark would measure the
benchmark rather than the application.

## Decision

Store strictly validated JSON datasets in versioned directories. Pin every repository to a full
commit SHA and require the matching snapshot and retrieval index to exist. Run benchmarks through
the production retriever, deterministic router, and controlled symbol lookup tool. Record the
dataset byte hash, snapshot IDs, embedding configuration, raw evidence, deterministic metrics,
latency, and configuration deltas in a versioned JSON report.

Define deterministic citation correctness as relevant, commit-pinned evidence with a valid indexed
line range. Keep any future model-assisted answer or groundedness scores in a clearly separate
report section with judge provenance.

## Consequences

Runs fail fast when their immutable prerequisite snapshot is missing, and results can be traced to
both labels and indexed code. Semantic and hybrid configurations can be compared without provider
calls. The runner intentionally does not auto-ingest a moving branch. Latency remains environment
dependent. Structural augmentation and reranking cannot be benchmarked as retrieval configurations
until those stages exist in the production retrieval path.
