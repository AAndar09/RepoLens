# ADR 0003: Bounded Git ingestion and immutable snapshots

- Status: Accepted
- Date: 2026-09-26

## Context

RepoLens must acquire public GitHub source safely, associate intelligence with an exact commit, tolerate malformed input, and remain repeatable. Repository contents are untrusted and can be unexpectedly large.

## Decision

Acquire only previously canonicalized GitHub HTTPS URLs using a shallow, non-recursive Git clone into an automatically deleted temporary directory. Disable interactive credentials, repository hooks, global/system Git configuration, and LFS smudging. Never import or execute acquired code.

Represent each analyzed commit as an immutable relational snapshot identified by repository and full commit SHA. Persist bounded source text, hashes, AST-derived symbols, imports, and parse outcomes beneath that snapshot. Return an existing ready snapshot when the same commit is ingested again.

Apply configuration-driven limits to clone time/size, accepted file count, aggregate source bytes, and individual file bytes. Syntax errors are file-level results; aggregate limit violations fail the snapshot without partial file persistence.

Run ingestion synchronously for Phase 2. Durable repository/snapshot statuses preserve visibility and allow a later queue implementation without changing the domain model.

## Consequences

- Results and future citations can be tied to stable commits rather than moving branches.
- Large or unsuitable repositories fail predictably, and repository code never runs.
- A repeat request still performs a shallow clone to resolve the current default-branch commit.
- HTTP requests can remain open for the configured clone duration; production scaling may later require background jobs.
- Force-pushed commits remain queryable because stored intelligence belongs to the recorded SHA.

