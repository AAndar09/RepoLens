from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes.repositories import get_repository_acquirer
from app.main import app
from app.services.acquisition import AcquiredRepository


class CheckoutAcquirer:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def acquire(self, github_url: str) -> Iterator[AcquiredRepository]:
        yield AcquiredRepository(path=self.path, branch="trunk", commit_sha="b" * 40)


def test_ingestion_and_intelligence_query_endpoints(
    client: TestClient, tmp_path: Path
) -> None:
    (tmp_path / "example.py").write_text(
        "from pathlib import Path\n\ndef location() -> Path:\n    return Path('.')\n",
        encoding="utf-8",
    )
    app.dependency_overrides[get_repository_acquirer] = lambda: CheckoutAcquirer(tmp_path)
    repository_response = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://github.com/example/queryable"},
    )
    repository_id = repository_response.json()["id"]

    ingestion_response = client.post(f"/api/v1/repositories/{repository_id}/ingestions")

    assert ingestion_response.status_code == 200
    snapshot = ingestion_response.json()
    assert snapshot["branch"] == "trunk"
    assert snapshot["commit_sha"] == "b" * 40
    assert snapshot["status"] == "ready"
    assert snapshot["file_count"] == 1
    snapshot_id = snapshot["id"]

    repository = client.get(f"/api/v1/repositories/{repository_id}").json()
    assert repository["status"] == "ready"

    snapshots = client.get(f"/api/v1/repositories/{repository_id}/snapshots").json()
    assert [item["id"] for item in snapshots] == [snapshot_id]

    files = client.get(
        f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/files"
    ).json()
    assert files[0]["path"] == "example.py"
    file_detail = client.get(
        f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/files/{files[0]['id']}"
    ).json()
    assert "def location" in file_detail["content"]

    symbols = client.get(
        f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/symbols",
        params={"kind": "function"},
    ).json()
    assert symbols[0]["qualified_name"] == "example.location"
    assert symbols[0]["start_line"] == 3

    imports = client.get(
        f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/imports"
    ).json()
    assert imports[0]["module"] == "pathlib"
    assert imports[0]["imported_name"] == "Path"

