# ADR 0008: Persist manifest provenance and query OSV only for exact versions

## Status

Accepted

## Context

Dependency declarations range from exact pins to open constraints and environment-dependent markers. OSV's package query is version-specific. Treating a range as an installed version would create misleading vulnerability matches, while losing the original declaration would make findings difficult to audit.

## Decision

Extract PEP 508 dependencies deterministically from `requirements*.txt` and PEP 621 `pyproject.toml` tables. Persist every valid declaration with its snapshot, manifest path, line, scope, marker, specifier, and normalized PyPI name. Mark a version resolved only for one non-wildcard `==` or `===` pin.

Use a dedicated OSV client and query `POST /v1/query` only for resolved PyPI versions. Persist successful query time even when no vulnerabilities are returned, and cache normalized findings plus the raw OSV record and source URL. Retain prior findings if a refresh fails. Unpinned dependencies remain visible and explicitly unscanned.

## Consequences

Findings are reproducible and traceable to both an immutable repository snapshot and OSV. Lock-file resolution and transitive dependency resolution are not claimed. An OSV match means the declared version appears in a public vulnerability record; it does not establish reachability or exploitability in the application.
