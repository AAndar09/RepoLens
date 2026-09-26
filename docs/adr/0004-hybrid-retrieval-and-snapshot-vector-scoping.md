# ADR 0004: Use snapshot-scoped hybrid retrieval

## Status

Accepted

## Context

Code retrieval must preserve commit-specific evidence while supporting exact identifier lookup and
meaning-oriented discovery. A vector store alone does not own durable source metadata.

## Decision

Persist symbol-aware retrieval units in the relational database. Use a configurable local embedding
provider and Qdrant vectors with a mandatory snapshot payload. Rank lexical and semantic results
independently, then combine them using reciprocal-rank fusion. Resolve vector hits through the
snapshot's relational index before returning evidence.

## Consequences

Results are reproducible for a fixed provider/configuration and cannot cross snapshots. The default
hashing embeddings are lightweight and local but lower quality than a learned code embedding model;
that provider can be introduced later behind the same interface.
