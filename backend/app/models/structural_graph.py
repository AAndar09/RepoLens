import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.snapshot import RepositorySnapshot
    from app.models.source_file import SourceFile
    from app.models.source_import import SourceImport


class ImportResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


class ModuleImportResolution(Base):
    __tablename__ = "module_import_resolutions"
    __table_args__ = (
        UniqueConstraint("source_import_id", name="uq_import_resolutions_source_import"),
        Index("ix_import_resolutions_snapshot_status", "snapshot_id", "status"),
        Index("ix_import_resolutions_target", "snapshot_id", "target_source_file_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    source_import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_imports.id", ondelete="CASCADE"), nullable=False
    )
    target_source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[ImportResolutionStatus] = mapped_column(
        Enum(ImportResolutionStatus, native_enum=False, length=32), nullable=False
    )
    requested_module: Mapped[str] = mapped_column(String(2048), nullable=False)
    resolved_module: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    candidate_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    snapshot: Mapped["RepositorySnapshot"] = relationship(
        back_populates="module_import_resolutions"
    )
    source_import: Mapped["SourceImport"] = relationship(back_populates="resolution")
    target_source_file: Mapped["SourceFile | None"] = relationship(
        foreign_keys=[target_source_file_id]
    )
