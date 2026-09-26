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

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.retrieval import SnapshotRetrievalIndex
    from app.models.source_file import SourceFile
    from app.models.structural_graph import ModuleImportResolution


class SnapshotStatus(StrEnum):
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"


class RepositorySnapshot(Base):
    __tablename__ = "repository_snapshots"
    __table_args__ = (
        UniqueConstraint("repository_id", "commit_sha", name="uq_snapshots_repository_commit"),
        Index("ix_snapshots_repository_created", "repository_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[SnapshotStatus] = mapped_column(
        Enum(SnapshotStatus, native_enum=False, length=32),
        nullable=False,
        default=SnapshotStatus.INGESTING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    malformed_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    symbol_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    import_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repository: Mapped["Repository"] = relationship(back_populates="snapshots")
    files: Mapped[list["SourceFile"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="SourceFile.path",
    )
    retrieval_index: Mapped["SnapshotRetrievalIndex | None"] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        uselist=False,
    )
    module_import_resolutions: Mapped[list["ModuleImportResolution"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
