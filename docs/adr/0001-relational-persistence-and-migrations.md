# ADR 0001: Relational persistence and migrations

- Status: Accepted
- Date: 2026-09-26

## Context

RepoLens requires relational application data, targets PostgreSQL in production, and permits a simpler compatible development setup. The foundation must support explicit schema initialization without coupling HTTP application startup to table creation.

## Decision

Use SQLAlchemy 2 as the persistence abstraction and Alembic as the schema migration authority. Docker Compose uses PostgreSQL. Native development and automated tests may use SQLite through the same model and session interfaces.

The application does not call `create_all` at startup. Deployments and local workflows apply `alembic upgrade head` before serving requests.

## Consequences

- PostgreSQL-specific behavior must be tested when such behavior is introduced.
- Models should remain portable until a documented need for database-specific features arises.
- Schema changes require migrations, making deployment state explicit and repeatable.

