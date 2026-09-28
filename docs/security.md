# Security review

Remote repository contents are untrusted data. RepoLens does not execute repository code, install
its packages, initialize submodules, run Git hooks, or allow the agent shell/filesystem access.

## Implemented controls

- Submission accepts canonical public `https://github.com/{owner}/{repo}` URLs only; credentials,
  query strings, fragments, extra paths, and other hosts are rejected.
- Git uses a shallow, single-branch, no-tags, blob-filtered clone with prompts, hooks, global/system
  config, LFS smudging, submodules, `file`, and `ext` transports disabled.
- Symlinks are not followed or indexed. Source count, per-file bytes, aggregate source bytes, clone
  size, dependency records, retrieval units, tool calls, evidence, and model context are bounded.
- Requests have body and route-specific rate limits; ingestion also has concurrency and queued-job
  caps. Production validates CORS/Host configuration,
  serves explicit browser security headers, hides API docs, and uses same-origin API proxying.
- Provider credentials remain backend-only and structured logs omit request bodies, source, prompts,
  and secrets. Agent tools are an allowlisted application interface.
- Containers run non-root; production backend filesystems are read-only except bounded `/tmp`.

## Residual risks

The in-memory rate limiter is per process and is not a substitute for edge/WAF limits. Clone size is
checked after Git materializes the shallow checkout, so the container also needs disk/memory quotas
and egress policy. Public source may contain malicious text intended to influence an LLM; controlled
tools and no execution limit impact, but generated explanations remain untrusted output. OSV matches
do not establish exploitability. v1 has no authentication, tenant isolation, malware scanner,
network allowlist proxy, or automated data retention.
