import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.repositories import _snapshot_or_404
from app.config import Settings, get_settings
from app.database import get_session
from app.dependencies.osv import OsvClient, VulnerabilityProvider
from app.dependencies.service import VulnerabilityIntelligenceService
from app.models.dependency import DependencyVulnerability, SnapshotDependency
from app.models.snapshot import SnapshotStatus
from app.schemas.dependency import (
    DependencyResponse,
    VulnerabilityResponse,
    VulnerabilityScanResponse,
)

router = APIRouter(prefix="/repositories", tags=["dependencies"])


def get_vulnerability_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VulnerabilityProvider:
    return OsvClient(settings)


def _finding_response(
    finding: DependencyVulnerability, dependency: SnapshotDependency
) -> VulnerabilityResponse:
    return VulnerabilityResponse(
        id=finding.id,
        dependency_id=dependency.id,
        package_name=dependency.name,
        package_version=dependency.resolved_version or "",
        osv_id=finding.osv_id,
        summary=finding.summary,
        details=finding.details,
        aliases=finding.aliases,
        severity=finding.severity,
        affected=finding.affected,
        references=finding.references,
        published=finding.published,
        modified=finding.modified,
        source=finding.source,
        source_url=finding.source_url,
        queried_at=finding.queried_at,
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/dependencies",
    response_model=list[DependencyResponse],
)
def list_dependencies(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SnapshotDependency]:
    _snapshot_or_404(session, repository_id, snapshot_id)
    return list(
        session.scalars(
            select(SnapshotDependency)
            .where(SnapshotDependency.snapshot_id == snapshot_id)
            .order_by(SnapshotDependency.normalized_name, SnapshotDependency.source_path)
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/vulnerabilities",
    response_model=list[VulnerabilityResponse],
)
def list_vulnerabilities(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[VulnerabilityResponse]:
    _snapshot_or_404(session, repository_id, snapshot_id)
    rows = session.execute(
        select(DependencyVulnerability, SnapshotDependency)
        .join(SnapshotDependency, SnapshotDependency.id == DependencyVulnerability.dependency_id)
        .where(SnapshotDependency.snapshot_id == snapshot_id)
        .order_by(SnapshotDependency.normalized_name, DependencyVulnerability.osv_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return [_finding_response(finding, dependency) for finding, dependency in rows]


@router.post(
    "/{repository_id}/snapshots/{snapshot_id}/vulnerability-scan",
    response_model=VulnerabilityScanResponse,
)
def scan_vulnerabilities(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[VulnerabilityProvider, Depends(get_vulnerability_provider)],
    refresh: bool = False,
    finding_limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> VulnerabilityScanResponse:
    snapshot = _snapshot_or_404(session, repository_id, snapshot_id)
    if snapshot.status != SnapshotStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only ready snapshots can be scanned",
        )
    before = {item.id: item.vulnerability_checked_at for item in snapshot.dependencies}
    dependencies = VulnerabilityIntelligenceService(session, provider).scan(
        snapshot, refresh=refresh
    )
    rows = session.execute(
        select(DependencyVulnerability, SnapshotDependency)
        .join(SnapshotDependency, SnapshotDependency.id == DependencyVulnerability.dependency_id)
        .where(SnapshotDependency.snapshot_id == snapshot_id)
        .order_by(SnapshotDependency.normalized_name, DependencyVulnerability.osv_id)
        .limit(finding_limit)
    ).all()
    finding_count = session.scalar(
        select(func.count())
        .select_from(DependencyVulnerability)
        .join(SnapshotDependency, SnapshotDependency.id == DependencyVulnerability.dependency_id)
        .where(SnapshotDependency.snapshot_id == snapshot_id)
    )
    findings = [_finding_response(finding, dependency) for finding, dependency in rows]
    return VulnerabilityScanResponse(
        snapshot_id=snapshot.id,
        dependency_count=len(dependencies),
        queried_count=sum(
            item.version_resolved
            and (refresh or before.get(item.id) is None)
            and item.vulnerability_check_error is None
            for item in dependencies
        ),
        unresolved_version_count=sum(not item.version_resolved for item in dependencies),
        failed_count=sum(item.vulnerability_check_error is not None for item in dependencies),
        finding_count=finding_count or 0,
        findings=findings,
    )
