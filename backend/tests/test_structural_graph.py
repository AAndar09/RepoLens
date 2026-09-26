from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes.repositories import get_repository_acquirer
from app.main import app
from app.services.acquisition import AcquiredRepository


class GraphCheckoutAcquirer:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def acquire(self, github_url: str) -> Iterator[AcquiredRepository]:
        yield AcquiredRepository(path=self.path, branch="main", commit_sha="c" * 40)


def _ingest_graph_fixture(client: TestClient, root: Path) -> tuple[str, str]:
    package = root / "package"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .service import Greeter\n", encoding="utf-8"
    )
    (package / "service.py").write_text(
        "class Greeter:\n    def greet(self):\n        return 'hello'\n",
        encoding="utf-8",
    )
    source_root = root / "src"
    source_root.mkdir()
    (source_root / "pkg.py").write_text("value = 'src'\n", encoding="utf-8")
    (root / "pkg.py").write_text("value = 'root'\n", encoding="utf-8")
    (root / "consumer.py").write_text(
        "import pkg\nimport external_dependency\n", encoding="utf-8"
    )

    app.dependency_overrides[get_repository_acquirer] = lambda: GraphCheckoutAcquirer(root)
    repository = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://github.com/example/structural-graph"},
    ).json()
    snapshot = client.post(
        f"/api/v1/repositories/{repository['id']}/ingestions"
    ).json()
    return repository["id"], snapshot["id"]


def test_graph_queries_resolve_containment_importers_and_uncertainty(
    client: TestClient, tmp_path: Path
) -> None:
    repository_id, snapshot_id = _ingest_graph_fixture(client, tmp_path)
    base = f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}"

    summary = client.get(f"{base}/graph")
    assert summary.status_code == 200
    assert summary.json() == {
        "snapshot_id": snapshot_id,
        "module_count": 5,
        "symbol_count": 7,
        "import_count": 3,
        "resolved_import_count": 1,
        "unresolved_import_count": 1,
        "ambiguous_import_count": 1,
        "complete": True,
    }

    files = client.get(f"{base}/files").json()
    file_ids = {item["path"]: item["id"] for item in files}
    consumer_imports = client.get(
        f"{base}/graph/modules/{file_ids['consumer.py']}/imports"
    ).json()
    assert consumer_imports[0]["status"] == "ambiguous"
    assert consumer_imports[0]["candidate_paths"] == ["pkg.py", "src/pkg.py"]
    assert consumer_imports[1]["status"] == "unresolved"
    assert consumer_imports[1]["target_module"] is None

    package_imports = client.get(
        f"{base}/graph/modules/{file_ids['package/__init__.py']}/imports"
    ).json()
    assert package_imports[0]["status"] == "resolved"
    assert package_imports[0]["target_module"]["path"] == "package/service.py"

    importers = client.get(
        f"{base}/graph/modules/{file_ids['package/service.py']}/importers"
    ).json()
    assert [item["source_module"]["path"] for item in importers] == [
        "package/__init__.py"
    ]

    symbols = client.get(
        f"{base}/graph/modules/{file_ids['package/service.py']}/symbols"
    ).json()
    symbol_ids = {item["name"]: item["id"] for item in symbols}
    containment = client.get(
        f"{base}/graph/symbols/{symbol_ids['Greeter']}/containment"
    ).json()
    assert containment["parent"]["kind"] == "module"
    assert [item["name"] for item in containment["children"]] == ["greet"]


def test_graph_rebuild_is_repeatable(client: TestClient, tmp_path: Path) -> None:
    repository_id, snapshot_id = _ingest_graph_fixture(client, tmp_path)
    url = f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/graph"
    first = client.post(url)
    second = client.post(url)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
