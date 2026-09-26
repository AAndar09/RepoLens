from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.tools import ControlledToolset
from app.api.routes.dependencies import get_vulnerability_provider
from app.config import Settings
from app.dependencies.extraction import PythonDependencyExtractor
from app.dependencies.osv import OsvClient, OsvError
from app.dependencies.service import VulnerabilityIntelligenceService
from app.main import app
from app.models.dependency import DependencyVulnerability, SnapshotDependency
from app.models.repository import Repository, RepositoryStatus
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.schemas.investigation import ToolRequest


class FakeOsv:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def query(self, ecosystem: str, package: str, version: str):
        self.calls.append((ecosystem, package, version))
        return [
            {
                "id": "OSV-TEST-1",
                "summary": "Test vulnerability",
                "aliases": ["CVE-2099-0001"],
                "severity": [{"type": "CVSS_V3", "score": "7.5"}],
                "affected": [{"package": {"name": package, "ecosystem": ecosystem}}],
                "references": [{"type": "ADVISORY", "url": "https://example.test/advisory"}],
                "published": "2099-01-01T00:00:00Z",
                "modified": "2099-01-02T00:00:00Z",
            }
        ]


def test_osv_client_sends_version_specific_pypi_query(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return httpx.Response(
            200,
            json={"vulns": [{"id": "OSV-TEST-HTTP"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    rows = OsvClient(Settings(_env_file=None)).query("PyPI", "requests", "2.31.0")

    assert rows == [{"id": "OSV-TEST-HTTP"}]
    assert captured["url"] == "https://api.osv.dev/v1/query"
    assert captured["json"] == {
        "package": {"ecosystem": "PyPI", "name": "requests"},
        "version": "2.31.0",
    }


def test_osv_client_wraps_external_api_failure(monkeypatch) -> None:
    def fake_post(url, *, json, timeout):
        del json, timeout
        return httpx.Response(503, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(OsvError, match="requests 2.31.0"):
        OsvClient(Settings(_env_file=None)).query("PyPI", "requests", "2.31.0")


def test_extracts_requirements_and_pyproject_with_provenance(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests==2.31.0\nflask>=3\n-r dev.txt\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["httpx==0.28.1"]\n'
        '[project.optional-dependencies]\ntest = ["pytest>=8"]\n',
        encoding="utf-8",
    )

    dependencies = PythonDependencyExtractor(100_000).extract(tmp_path)
    by_name = {item.normalized_name: item for item in dependencies}

    assert by_name["requests"].resolved_version == "2.31.0"
    assert by_name["requests"].source_path == "requirements.txt"
    assert by_name["flask"].resolved_version is None
    assert by_name["httpx"].resolved_version == "0.28.1"
    assert by_name["pytest"].scope == "optional:test"


def _seed_dependencies(session):
    repository = Repository(
        github_url="https://github.com/acme/dependencies",
        owner="acme",
        name="dependencies",
        status=RepositoryStatus.READY,
    )
    snapshot = RepositorySnapshot(
        repository=repository,
        branch="main",
        commit_sha="e" * 40,
        status=SnapshotStatus.READY,
    )
    pinned = SnapshotDependency(
        snapshot=snapshot,
        ecosystem="PyPI",
        name="requests",
        normalized_name="requests",
        specifier="==2.31.0",
        resolved_version="2.31.0",
        version_resolved=True,
        source_type="REQUIREMENTS",
        source_path="requirements.txt",
        source_line=1,
        declaration="requests==2.31.0",
        scope="runtime",
    )
    unpinned = SnapshotDependency(
        snapshot=snapshot,
        ecosystem="PyPI",
        name="flask",
        normalized_name="flask",
        specifier=">=3",
        version_resolved=False,
        source_type="REQUIREMENTS",
        source_path="requirements.txt",
        source_line=2,
        declaration="flask>=3",
        scope="runtime",
    )
    session.add_all([repository, snapshot, pinned, unpinned])
    session.commit()
    return repository, snapshot, pinned, unpinned


def test_osv_findings_are_persisted_and_unpinned_dependencies_are_skipped(
    session_factory,
) -> None:
    provider = FakeOsv()
    with session_factory() as session:
        _, snapshot, pinned, unpinned = _seed_dependencies(session)
        service = VulnerabilityIntelligenceService(session, provider)
        service.scan(snapshot)
        service.scan(snapshot)

        finding = session.scalar(select(DependencyVulnerability))
        assert finding is not None
        assert finding.osv_id == "OSV-TEST-1"
        assert finding.source == "OSV"
        assert finding.source_url.endswith("OSV-TEST-1")
        assert pinned.vulnerability_checked_at is not None
        assert unpinned.vulnerability_checked_at is None
        assert provider.calls == [("PyPI", "requests", "2.31.0")]


def test_vulnerability_api_uses_mocked_external_provider(
    client: TestClient, session_factory
) -> None:
    provider = FakeOsv()
    with session_factory() as session:
        repository, snapshot, _, _ = _seed_dependencies(session)
        repository_id, snapshot_id = repository.id, snapshot.id

    app.dependency_overrides[get_vulnerability_provider] = lambda: provider
    response = client.post(
        f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/vulnerability-scan"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["queried_count"] == 1
    assert body["unresolved_version_count"] == 1
    assert body["findings"][0]["source"] == "OSV"


def test_controlled_security_tool_returns_osv_and_manifest_facts(session_factory) -> None:
    provider = FakeOsv()
    settings = Settings(_env_file=None, embedding_dimensions=16)
    with session_factory() as session:
        repository, snapshot, _, _ = _seed_dependencies(session)
        tools = ControlledToolset(
            session,
            settings,
            repository,
            snapshot,
            vector_store=None,
            embedding_provider=None,
            vulnerability_provider=provider,
        )
        result = tools.execute(
            ToolRequest(
                tool="check_vulnerabilities",
                arguments={"package": "requests"},
                purpose="Check the dependency against OSV",
            )
        )

    assert result.evidence[0].data["evidence_type"] == "external_vulnerability_fact"
    assert result.evidence[0].data["source"] == "OSV"
    assert "not proof" in result.summary
