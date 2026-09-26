"""Add repository snapshots and Python source intelligence.

Revision ID: 20260926_0002
Revises: 20260926_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0002"
down_revision: str | None = "20260926_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("ingestion_error", sa.Text(), nullable=True))
    op.create_table(
        "repository_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "INGESTING",
                "READY",
                "FAILED",
                name="snapshotstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("parsed_file_count", sa.Integer(), nullable=False),
        sa.Column("malformed_file_count", sa.Integer(), nullable=False),
        sa.Column("skipped_file_count", sa.Integer(), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False),
        sa.Column("import_count", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id", "commit_sha", name="uq_snapshots_repository_commit"
        ),
    )
    op.create_index(
        "ix_snapshots_repository_created",
        "repository_snapshots",
        ["repository_id", "created_at"],
    )
    op.create_table(
        "source_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("module_name", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column(
            "parse_status",
            sa.Enum(
                "PARSED", "MALFORMED", name="fileparsestatus", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["repository_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "path", name="uq_source_files_snapshot_path"),
    )
    op.create_index("ix_source_files_snapshot_path", "source_files", ["snapshot_id", "path"])
    op.create_table(
        "code_symbols",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "MODULE",
                "CLASS",
                "FUNCTION",
                "METHOD",
                name="symbolkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("qualified_name", sa.String(length=2048), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("is_async", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["code_symbols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_symbols_file_kind", "code_symbols", ["source_file_id", "kind"])
    op.create_index("ix_code_symbols_qualified_name", "code_symbols", ["qualified_name"])
    op.create_table(
        "source_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.String(length=1024), nullable=False),
        sa.Column("imported_name", sa.String(length=255), nullable=True),
        sa.Column("alias", sa.String(length=255), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_imports_file_module", "source_imports", ["source_file_id", "module"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_imports_file_module", table_name="source_imports")
    op.drop_table("source_imports")
    op.drop_index("ix_code_symbols_qualified_name", table_name="code_symbols")
    op.drop_index("ix_code_symbols_file_kind", table_name="code_symbols")
    op.drop_table("code_symbols")
    op.drop_index("ix_source_files_snapshot_path", table_name="source_files")
    op.drop_table("source_files")
    op.drop_index("ix_snapshots_repository_created", table_name="repository_snapshots")
    op.drop_table("repository_snapshots")
    op.drop_column("repositories", "ingestion_error")
