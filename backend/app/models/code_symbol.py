import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.source_file import SourceFile


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


class CodeSymbol(Base):
    __tablename__ = "code_symbols"
    __table_args__ = (
        Index("ix_code_symbols_file_kind", "source_file_id", "kind"),
        Index("ix_code_symbols_qualified_name", "qualified_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[SymbolKind] = mapped_column(
        Enum(SymbolKind, native_enum=False, length=32), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(2048), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    is_async: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source_file: Mapped["SourceFile"] = relationship(
        back_populates="symbols", foreign_keys=[source_file_id]
    )
    parent: Mapped["CodeSymbol | None"] = relationship(
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list["CodeSymbol"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        single_parent=True,
    )
