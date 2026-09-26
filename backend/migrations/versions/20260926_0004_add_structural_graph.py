"""Add deterministic module import resolutions.

Revision ID: 20260926_0004
Revises: 20260926_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0004"
down_revision: str | None = "20260926_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_import_resolutions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("source_import_id", sa.Uuid(), nullable=False),
        sa.Column("target_source_file_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "RESOLVED",
                "UNRESOLVED",
                "AMBIGUOUS",
                name="importresolutionstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("requested_module", sa.String(length=2048), nullable=False),
        sa.Column("resolved_module", sa.String(length=1024), nullable=True),
        sa.Column("candidate_paths", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["repository_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_import_id"], ["source_imports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_source_file_id"], ["source_files.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_import_id", name="uq_import_resolutions_source_import"
        ),
    )
    op.create_index(
        "ix_import_resolutions_snapshot_status",
        "module_import_resolutions",
        ["snapshot_id", "status"],
    )
    op.create_index(
        "ix_import_resolutions_target",
        "module_import_resolutions",
        ["snapshot_id", "target_source_file_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_resolutions_target", table_name="module_import_resolutions")
    op.drop_index(
        "ix_import_resolutions_snapshot_status", table_name="module_import_resolutions"
    )
    op.drop_table("module_import_resolutions")
