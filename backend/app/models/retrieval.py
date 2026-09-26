import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.code_symbol import SymbolKind

if TYPE_CHECKING:
    from app.models.snapshot import RepositorySnapshot


class RetrievalIndexStatus(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class SnapshotRetrievalIndex(Base):
    __tablename__ = "snapshot_retrieval_indexes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[RetrievalIndexStatus] = mapped_column(
        Enum(RetrievalIndexStatus, native_enum=False, length=32),
        nullable=False,
        default=RetrievalIndexStatus.PENDING,
    )
    embedding_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    snapshot: Mapped["RepositorySnapshot"] = relationship(back_populates="retrieval_index")
    units: Mapped[list["RetrievalUnit"]] = relationship(
        back_populates="retrieval_index",
        cascade="all, delete-orphan",
        order_by="RetrievalUnit.filepath, RetrievalUnit.start_line",
    )


class RetrievalUnit(Base):
    __tablename__ = "retrieval_units"
    __table_args__ = (
        UniqueConstraint("retrieval_index_id", "unit_key", name="uq_retrieval_units_index_key"),
        Index(
            "ix_retrieval_units_index_filters",
            "retrieval_index_id",
            "language",
            "filepath",
            "symbol_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    retrieval_index_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("snapshot_retrieval_indexes.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False
    )
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=True
    )
    unit_key: Mapped[str] = mapped_column(String(300), nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    filepath: Mapped[str] = mapped_column(String(1024), nullable=False)
    symbol_kind: Mapped[SymbolKind | None] = mapped_column(
        Enum(SymbolKind, native_enum=False, length=32), nullable=True
    )
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qualified_name: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)

    retrieval_index: Mapped["SnapshotRetrievalIndex"] = relationship(back_populates="units")
