# ADR 0010: Use provider-agnostic LLM inference with cloud-first demo deployment

## Status

Accepted

## Context

RepoLens initially used Ollama as its only generative inference adapter. Local inference proved
functional, but the available development hardware is CPU-bound for useful coding/agent models and
latency is unsuitable for the interactive multi-call LangGraph workflow. RepoLens is a low-traffic
portfolio application expected to receive fewer than five questions per day and currently analyses
only public GitHub repositories.

## Decision

Put generative inference behind one project-level provider contract and central factory. Use Gemini
as the intended primary cloud provider and Groq as one bounded fallback. Keep OpenRouter available
for experiments and Ollama for optional local/offline development and benchmarking. A provider
failure can invoke at most one fallback, and only timeout, connection, rate-limit, or server
availability errors qualify. Authentication, configuration, rejected requests, malformed output,
and normal model answers do not trigger fallback.

Use Gemini's native REST API and a small OpenAI-compatible HTTP adapter for Groq and OpenRouter,
avoiding new SDK dependencies and provider response types in application logic. Keep query routing
independent from generative inference. Keep hashing embeddings and Qdrant independent from generative inference.
Credentials remain backend-only and are checked lazily when their provider is invoked.

## Consequences

Cloud inference provides substantially better latency and model quality with negligible expected
demo cost, reduces dependence on local hardware, and makes model comparison straightforward.
Provider/model/latency/outcome and optional token usage are observable without logging prompts or
secrets.

The application now depends on an external API and internet connection for its intended deployment.
Free tiers, rate limits, and model availability can change. Source excerpts from public repositories
leave the application boundary when a cloud provider is used. Ollama remains available when that
trade-off is unacceptable. Provider structured-output capabilities differ, so RepoLens always
performs its own Pydantic validation.
