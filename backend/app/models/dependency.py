import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.snapshot import RepositorySnapshot


class DependencySourceType(StrEnum):
    REQUIREMENTS = "requirements"
    PYPROJECT = "pyproject"


class SnapshotDependency(Base):
    __tablename__ = "snapshot_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "source_path",
            "source_line",
            "normalized_name",
            name="uq_snapshot_dependency_provenance",
        ),
        Index("ix_snapshot_dependencies_snapshot_name", "snapshot_id", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    ecosystem: Mapped[str] = mapped_column(String(64), nullable=False, default="PyPI")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specifier: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resolved_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_type: Mapped[DependencySourceType] = mapped_column(
        Enum(DependencySourceType, native_enum=False, length=32), nullable=False
    )
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_line: Mapped[int | None] = mapped_column(nullable=True)
    declaration: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="runtime")
    marker: Mapped[str | None] = mapped_column(Text, nullable=True)
    vulnerability_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    vulnerability_check_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    snapshot: Mapped["RepositorySnapshot"] = relationship(back_populates="dependencies")
    vulnerabilities: Mapped[list["DependencyVulnerability"]] = relationship(
        back_populates="dependency", cascade="all, delete-orphan"
    )


class DependencyVulnerability(Base):
    __tablename__ = "dependency_vulnerabilities"
    __table_args__ = (
        UniqueConstraint("dependency_id", "osv_id", name="uq_dependency_vulnerability_osv"),
        Index("ix_dependency_vulnerabilities_dependency", "dependency_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dependency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("snapshot_dependencies.id", ondelete="CASCADE"), nullable=False
    )
    osv_id: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    severity: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    affected: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    references: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    published: Mapped[str | None] = mapped_column(String(64), nullable=True)
    modified: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="OSV")
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    raw_response: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    queried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    dependency: Mapped[SnapshotDependency] = relationship(back_populates="vulnerabilities")
