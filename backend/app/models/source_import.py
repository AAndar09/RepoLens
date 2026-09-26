import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.source_file import SourceFile
    from app.models.structural_graph import ModuleImportResolution


class SourceImport(Base):
    __tablename__ = "source_imports"
    __table_args__ = (Index("ix_source_imports_file_module", "source_file_id", "module"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False
    )
    module: Mapped[str] = mapped_column(String(1024), nullable=False)
    imported_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)

    source_file: Mapped["SourceFile"] = relationship(back_populates="imports")
    resolution: Mapped["ModuleImportResolution | None"] = relationship(
        back_populates="source_import",
        cascade="all, delete-orphan",
        uselist=False,
    )
