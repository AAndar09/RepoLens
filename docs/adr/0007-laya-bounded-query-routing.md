# ADR 0007: Use Laya only for bounded query routing

## Status

Accepted

## Context

RepoLens has deterministic retrieval and graph tools plus a bounded LangGraph investigator. Sending every question to the investigator is slower and unnecessarily invokes a generative model for simple snapshot or lookup requests.

## Decision

Use Laya's local typed-decision model to classify a question into a small, closed set of query categories. Map that category to one existing route: snapshot metadata, direct symbol lookup, hybrid retrieval, or the existing full investigation workflow. Laya neither reads repository content nor invokes tools.

The route and confidence are returned in the API response and logged. Results below the configured confidence threshold, malformed Laya responses, and unavailable Laya inference all use the conservative full-investigation fallback.

## Consequences

Simple queries can avoid the investigation model. Complex dependency and security questions remain with the existing bounded agent. Laya adds a local PyTorch/model dependency and downloads its model on first use; application startup remains unaffected because the router loads lazily.
