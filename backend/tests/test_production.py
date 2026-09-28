from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.middleware import InMemoryRateLimiter


def test_request_limits_and_security_headers(client: TestClient) -> None:
    health = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-request"})

    assert health.headers["X-Request-ID"] == "test-request"
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"

    response = client.post(
        "/api/v1/repositories",
        content=b"x" * 65_537,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_rate_limiter_enforces_window() -> None:
    limiter = InMemoryRateLimiter(maximum_clients=100)

    assert limiter.allow("query:client", 2, 60)[0] is True
    assert limiter.allow("query:client", 2, 60)[0] is True
    allowed, retry_after = limiter.allow("query:client", 2, 60)
    assert allowed is False
    assert retry_after > 0


def test_production_configuration_rejects_development_defaults() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="sqlite:///./test.db",
            cors_origins="https://repolens.example.com",
            allowed_hosts="repolens.example.com",
        )


def test_evaluation_results_endpoint_skips_invalid_reports(
    client: TestClient, tmp_path: Path
) -> None:
    fixture = Path(__file__).parents[1] / "evaluations" / "results" / "sampleproject.json"
    (tmp_path / "valid.json").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "invalid.json").write_text("not json", encoding="utf-8")
    settings = Settings(_env_file=None, evaluation_results_dir=str(tmp_path))
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.get("/api/v1/evaluations/results")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["dataset_id"] == "sampleproject.python.v1"
