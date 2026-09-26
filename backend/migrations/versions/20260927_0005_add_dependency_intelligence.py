"""Add snapshot dependency and OSV vulnerability intelligence.

Revision ID: 20260927_0005
Revises: 20260926_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0005"
down_revision: str | None = "20260926_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snapshot_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("ecosystem", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("specifier", sa.String(length=1024), nullable=True),
        sa.Column("resolved_version", sa.String(length=255), nullable=True),
        sa.Column("version_resolved", sa.Boolean(), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "REQUIREMENTS",
                "PYPROJECT",
                name="dependencysourcetype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("source_line", sa.Integer(), nullable=True),
        sa.Column("declaration", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("marker", sa.Text(), nullable=True),
        sa.Column("vulnerability_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vulnerability_check_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["repository_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "source_path",
            "source_line",
            "normalized_name",
            name="uq_snapshot_dependency_provenance",
        ),
    )
    op.create_index(
        "ix_snapshot_dependencies_snapshot_name",
        "snapshot_dependencies",
        ["snapshot_id", "normalized_name"],
    )
    op.create_table(
        "dependency_vulnerabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dependency_id", sa.Uuid(), nullable=False),
        sa.Column("osv_id", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("severity", sa.JSON(), nullable=False),
        sa.Column("affected", sa.JSON(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("published", sa.String(length=64), nullable=True),
        sa.Column("modified", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dependency_id"], ["snapshot_dependencies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dependency_id", "osv_id", name="uq_dependency_vulnerability_osv"),
    )
    op.create_index(
        "ix_dependency_vulnerabilities_dependency",
        "dependency_vulnerabilities",
        ["dependency_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dependency_vulnerabilities_dependency", table_name="dependency_vulnerabilities"
    )
    op.drop_table("dependency_vulnerabilities")
    op.drop_index("ix_snapshot_dependencies_snapshot_name", table_name="snapshot_dependencies")
    op.drop_table("snapshot_dependencies")
