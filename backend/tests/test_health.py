from fastapi.testclient import TestClient

from app.api.routes.health import get_readiness_vector_store
from app.main import app
from app.retrieval.vector_store import VectorStoreError


def test_health_reports_api_and_database_ready(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "vector_database": "ok",
    }


def test_liveness_does_not_require_dependencies(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_vector_database_failure(client: TestClient) -> None:
    class UnavailableVectorStore:
        def health_check(self) -> None:
            raise VectorStoreError("offline")

    app.dependency_overrides[get_readiness_vector_store] = UnavailableVectorStore

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Vector database is unavailable"
