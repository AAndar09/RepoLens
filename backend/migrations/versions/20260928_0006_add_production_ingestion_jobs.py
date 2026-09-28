"""Add production ingestion jobs and incremental-index counters.

Revision ID: 20260928_0006
Revises: 20260927_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0006"
down_revision: str | None = "20260927_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repository_snapshots",
        sa.Column("reused_file_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "repository_snapshots",
        sa.Column("processed_file_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "repository_snapshots",
        sa.Column("removed_file_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                name="ingestionjobstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["repository_snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_jobs_repository_id", "ingestion_jobs", ["repository_id"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_repository_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_column("repository_snapshots", "removed_file_count")
    op.drop_column("repository_snapshots", "processed_file_count")
    op.drop_column("repository_snapshots", "reused_file_count")
