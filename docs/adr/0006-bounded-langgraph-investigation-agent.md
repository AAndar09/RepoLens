# ADR 0006: Use a bounded LangGraph workflow with controlled application tools

## Status

Accepted

## Context

RepoLens needs iterative investigation and synthesis without giving a model direct access to the
host, repository checkout, database, vector infrastructure, or arbitrary network operations.
Planning and answers must also be machine-validated and observable.

## Decision

Use a custom LangGraph `StateGraph` with explicit plan, tool-execution, evidence-evaluation, and
synthesis nodes. Wrap the existing retrieval, relational symbol/source, and structural graph
services in five whitelisted tools. Validate tool arguments and all model responses with Pydantic.
Use a provider protocol with a local Ollama structured-output adapter as the initial implementation.
ADR 0010 supersedes the Ollama-first deployment choice while preserving this workflow.

Apply limits to investigation rounds, calls per round, evidence count, source lines, evaluation
evidence context, and LangGraph recursion. Model calls keep evidence identifiers and citations but
use bounded previews of oversized tool data, preventing source-heavy retrieval from exceeding a
local model's context window. Return per-call traces and accept only citations that reference source
evidence produced during that run. Do not use a generic prebuilt agent or give the model arbitrary
tools.

## Consequences

The control flow is testable without a live model, failures are visible, and snapshot scoping stays
inside application services. A configured generative provider is required only for routes that run
investigations. The synchronous HTTP request may be long-running; persistence, streaming, and job
execution can be added later without widening tool authority.
