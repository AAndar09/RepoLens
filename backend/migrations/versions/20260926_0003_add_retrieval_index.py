"""Add retrieval indexes and searchable units.

Revision ID: 20260926_0003
Revises: 20260926_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0003"
down_revision: str | None = "20260926_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snapshot_retrieval_indexes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "INDEXING",
                "READY",
                "FAILED",
                name="retrievalindexstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("embedding_provider", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column("unit_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["snapshot_id"], ["repository_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id"),
    )
    op.create_table(
        "retrieval_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_index_id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("symbol_id", sa.Uuid(), nullable=True),
        sa.Column("unit_key", sa.String(length=300), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("filepath", sa.String(length=1024), nullable=False),
        sa.Column(
            "symbol_kind",
            sa.Enum(
                "MODULE",
                "CLASS",
                "FUNCTION",
                "METHOD",
                name="symbolkind",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("qualified_name", sa.String(length=2048), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["retrieval_index_id"], ["snapshot_retrieval_indexes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symbol_id"], ["code_symbols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("retrieval_index_id", "unit_key", name="uq_retrieval_units_index_key"),
    )
    op.create_index(
        "ix_retrieval_units_index_filters",
        "retrieval_units",
        ["retrieval_index_id", "language", "filepath", "symbol_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_units_index_filters", table_name="retrieval_units")
    op.drop_table("retrieval_units")
    op.drop_table("snapshot_retrieval_indexes")

