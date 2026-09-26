# Phase 2 API

The API is rooted at `/api/v1`. Generated OpenAPI is available at `/openapi.json` and interactive documentation at `/docs`.

## Health

`GET /api/v1/health` checks the API and relational database. A healthy response is:

```json
{"status":"ok","database":"ok"}
```

## Repository submission and status

`POST /api/v1/repositories` validates and records one canonical public GitHub URL:

```json
{"github_url":"https://github.com/pypa/sampleproject"}
```

URLs must use HTTPS, use the exact `github.com` host, identify one owner/repository, and contain no credentials, query, or fragment. Invalid input returns `422`; a duplicate owner/repository returns `409`.

`GET /api/v1/repositories/{repository_id}` returns current repository status (`submitted`, `ingesting`, `ready`, or `failed`) and any ingestion error.

## Ingestion

`POST /api/v1/repositories/{repository_id}/ingestions` synchronously acquires and indexes the repository's default branch. The response contains:

- branch and full commit SHA;
- ingestion status and error;
- parsed, malformed, and skipped file counts;
- symbol/import counts and total accepted bytes.

The same completed commit is returned idempotently. Acquisition failures return `422`; configured resource-limit failures return `413`. Unexpected failures return `500` after repository/snapshot failure status is persisted.

`GET /api/v1/repositories/{repository_id}/snapshots` lists snapshot history newest first.

## Extracted intelligence

All collection endpoints accept bounded `limit` and `offset` parameters.

- `GET /api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/files`
- `GET /api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/files/{file_id}`
- `GET /api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/symbols`
- `GET /api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/imports`

The file-detail endpoint includes source content. Symbol queries optionally accept exact `kind` (`module`, `class`, `function`, or `method`) and `name` filters. Every symbol/import includes its source-file path and available line range.

## Retrieval

`POST /api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/retrieval-index` builds the
snapshot's vector and lexical index. It accepts optional `refresh=true`; otherwise a compatible
ready index is reused. `GET` on the same path reports its lifecycle and unit count.

`POST /api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/search` accepts:

```json
{"query":"where is authentication checked?","mode":"hybrid","limit":10,"symbol_kind":"function"}
```

`mode` is `lexical`, `semantic`, or `hybrid`; optional filters are `filepath`, `filepath_prefix`,
`symbol_kind`, and `language`. Evidence contains snapshot identity, code/path/line range, symbol
metadata, available score components, and a GitHub link pinned to its commit. An unindexed
snapshot returns `409`.
