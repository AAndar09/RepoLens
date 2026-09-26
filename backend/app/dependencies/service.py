from datetime import UTC, datetime

from packaging.utils import canonicalize_name
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.dependencies.osv import OsvError, VulnerabilityProvider
from app.models.dependency import DependencyVulnerability, SnapshotDependency
from app.models.snapshot import RepositorySnapshot


class VulnerabilityIntelligenceService:
    def __init__(self, session: Session, provider: VulnerabilityProvider) -> None:
        self.session = session
        self.provider = provider

    def scan(
        self,
        snapshot: RepositorySnapshot,
        *,
        refresh: bool = False,
        package: str | None = None,
    ) -> list[SnapshotDependency]:
        query = select(SnapshotDependency).where(SnapshotDependency.snapshot_id == snapshot.id)
        if package:
            query = query.where(SnapshotDependency.normalized_name == canonicalize_name(package))
        dependencies = list(
            self.session.scalars(query.order_by(SnapshotDependency.normalized_name))
        )
        for dependency in dependencies:
            if not dependency.version_resolved or dependency.resolved_version is None:
                continue
            if dependency.vulnerability_checked_at is not None and not refresh:
                continue
            try:
                findings = self.provider.query(
                    dependency.ecosystem,
                    dependency.name,
                    dependency.resolved_version,
                )
            except OsvError as exc:
                dependency.vulnerability_check_error = str(exc)[:2_000]
                self.session.commit()
                continue
            now = datetime.now(UTC)
            self.session.execute(
                delete(DependencyVulnerability).where(
                    DependencyVulnerability.dependency_id == dependency.id
                )
            )
            for finding in findings:
                osv_id = str(finding.get("id", "")).strip()
                if not osv_id:
                    continue
                dependency.vulnerabilities.append(
                    DependencyVulnerability(
                        osv_id=osv_id,
                        summary=self._optional_text(finding.get("summary")),
                        details=self._optional_text(finding.get("details")),
                        aliases=self._list_of_strings(finding.get("aliases")),
                        severity=self._list_of_dicts(finding.get("severity")),
                        affected=self._list_of_dicts(finding.get("affected")),
                        references=self._list_of_dicts(finding.get("references")),
                        published=self._optional_text(finding.get("published")),
                        modified=self._optional_text(finding.get("modified")),
                        source="OSV",
                        source_url=f"https://osv.dev/vulnerability/{osv_id}",
                        raw_response=finding,
                        queried_at=now,
                    )
                )
            dependency.vulnerability_checked_at = now
            dependency.vulnerability_check_error = None
            self.session.commit()
        return dependencies

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _list_of_strings(value: object) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _list_of_dicts(value: object) -> list[dict[str, object]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
