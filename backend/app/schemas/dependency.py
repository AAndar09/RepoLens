import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.dependency import DependencySourceType


class DependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    ecosystem: str
    name: str
    normalized_name: str
    specifier: str | None
    resolved_version: str | None
    version_resolved: bool
    source_type: DependencySourceType
    source_path: str
    source_line: int | None
    declaration: str
    scope: str
    marker: str | None
    vulnerability_checked_at: datetime | None
    vulnerability_check_error: str | None


class VulnerabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dependency_id: uuid.UUID
    package_name: str
    package_version: str
    osv_id: str
    summary: str | None
    details: str | None
    aliases: list[str]
    severity: list[dict[str, object]]
    affected: list[dict[str, object]]
    references: list[dict[str, object]]
    published: str | None
    modified: str | None
    source: str
    source_url: str
    queried_at: datetime


class VulnerabilityScanResponse(BaseModel):
    snapshot_id: uuid.UUID
    dependency_count: int
    queried_count: int
    unresolved_version_count: int
    failed_count: int
    finding_count: int
    findings: list[VulnerabilityResponse]
