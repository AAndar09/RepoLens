# Production deployment

RepoLens ships a single-host production Compose path. It uses PostgreSQL and Qdrant on an internal
network, a non-root/read-only backend container with a bounded writable `/tmp`, and Nginx for the
static frontend plus same-origin `/api` proxying.

## Configure and start

1. Copy `.env.production.example` to `.env.production`.
2. Replace the database password, public origin/host, model selection, and required provider key.
   Do not put secrets in either checked-in example file.
3. Terminate TLS at a trusted reverse proxy or load balancer in front of port 8080.
4. Start the stack:

```bash
docker compose --env-file .env.production -f compose.production.yaml up -d --build
```

Migrations run before Uvicorn starts. `/api/v1/health/live` checks the process only;
`/api/v1/health/ready` checks PostgreSQL and Qdrant and is the load-balancer readiness target.
Interactive API documentation is disabled in production.

Production settings reject SQLite, debug mode, wildcard/localhost CORS origins, and wildcard host
allowlists. `REPOLENS_ALLOWED_HOSTS` must contain the public Host header. Only enable
`REPOLENS_TRUST_PROXY_HEADERS` behind a proxy that overwrites `X-Forwarded-For`.

## Scaling and updates

The v1 ingestion dispatcher is bounded but process-local. Run one backend process/container. A
multi-replica deployment requires a durable external queue and database job leases first. Query
traffic can be split into separate replicas only after ingestion dispatch is separated.

Before an update, back up PostgreSQL, then build images and run the normal Compose update. Alembic
migrations are forward-applied automatically. Review migrations before production rollout and test
restore procedures in a non-production environment.

See [operations](operations.md) for backups/recovery and [security](security.md) for the untrusted
repository threat model.
