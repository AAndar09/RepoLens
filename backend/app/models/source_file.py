import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.code_symbol import CodeSymbol
    from app.models.snapshot import RepositorySnapshot
    from app.models.source_import import SourceImport


class FileParseStatus(StrEnum):
    PARSED = "parsed"
    MALFORMED = "malformed"


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "path", name="uq_source_files_snapshot_path"),
        Index("ix_source_files_snapshot_path", "snapshot_id", "path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    module_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_status: Mapped[FileParseStatus] = mapped_column(
        Enum(FileParseStatus, native_enum=False, length=32), nullable=False
    )
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    snapshot: Mapped["RepositorySnapshot"] = relationship(back_populates="files")
    symbols: Mapped[list["CodeSymbol"]] = relationship(
        back_populates="source_file",
        cascade="all, delete-orphan",
        foreign_keys="CodeSymbol.source_file_id",
    )
    imports: Mapped[list["SourceImport"]] = relationship(
        back_populates="source_file",
        cascade="all, delete-orphan",
    )

