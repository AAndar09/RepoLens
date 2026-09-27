# ADR 0011: Replace Laya with deterministic query routing

## Status

Accepted; supersedes ADR 0007

## Context

Laya classified questions before RepoLens selected direct retrieval or the LangGraph investigator.
It introduced PyTorch, Transformers, model downloads, multi-gigabyte Docker layers, and local
inference startup cost for a small closed routing problem. It also failed unpredictably in the
development container, sending otherwise clear questions to the fallback route.

RepoLens now uses configurable cloud models for investigation planning and synthesis. Query routing
does not need a second AI runtime: clear metadata, symbol, architecture, implementation, and
documentation requests have stable lexical signals, while uncertain questions already have a safe
general investigation path.

## Decision

Remove Laya and its configuration/dependencies. Use a deterministic, observable classifier for
clear query shapes. Preserve the existing typed categories, strategies, response metadata, and
labelled routing evaluation. Route ambiguous or unmatched questions to the bounded LangGraph
investigator.

## Consequences

Backend images no longer install PyTorch/CUDA solely for routing, builds are substantially smaller,
startup requires no routing-model download, and routing is reproducible. The rule set does not
attempt general natural-language understanding; unfamiliar phrasing deliberately uses the more
capable cloud investigation path. New narrow routes require explicit rules and evaluation examples.
