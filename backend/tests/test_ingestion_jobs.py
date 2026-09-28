from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.repositories import get_ingestion_job_runner
from app.config import Settings, get_settings
from app.main import app
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.repository import RepositoryStatus
from app.services.ingestion_jobs import (
    execute_ingestion_job,
    recover_interrupted_ingestion_jobs,
)
from tests.test_ingestion import FakeAcquirer, create_repository


class RecordingVectorStore:
    def __init__(self) -> None:
        self.replacements = 0

    def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        return None

    def replace_snapshot(self, collection_name, snapshot_id, points) -> None:
        self.replacements += 1


def test_ingestion_job_runs_analysis_and_retrieval_indexing(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    (tmp_path / "example.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    settings = Settings(_env_file=None)
    vector_store = RecordingVectorStore()
    with session_factory() as session:
        repository = create_repository(session)
        job = IngestionJob(repository_id=repository.id)
        session.add(job)
        session.commit()

        result = execute_ingestion_job(
            session,
            job,
            settings,
            acquirer=FakeAcquirer(tmp_path),
            vector_store=vector_store,
        )

        assert result.status == IngestionJobStatus.SUCCEEDED
        assert result.snapshot_id is not None
        assert result.attempt_count == 1
        assert vector_store.replacements == 1


def test_startup_recovery_marks_interrupted_jobs_retryable(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        repository = create_repository(session)
        repository.status = RepositoryStatus.INGESTING
        session.add_all(
            [
                IngestionJob(repository_id=repository.id),
                IngestionJob(
                    repository_id=repository.id,
                    status=IngestionJobStatus.RUNNING,
                ),
            ]
        )
        session.commit()

        assert recover_interrupted_ingestion_jobs(session) == 2

        assert all(
            item.status == IngestionJobStatus.FAILED
            for item in session.query(IngestionJob).all()
        )
        session.refresh(repository)
        assert repository.status == RepositoryStatus.FAILED
        assert repository.ingestion_error and "retry" in repository.ingestion_error


def test_failed_ingestion_job_persists_diagnostic(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    (tmp_path / "one.py").write_text("one = 1\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("two = 2\n", encoding="utf-8")
    settings = Settings(_env_file=None, ingestion_max_files=1)
    with session_factory() as session:
        repository = create_repository(session)
        job = IngestionJob(repository_id=repository.id)
        session.add(job)
        session.commit()

        with pytest.raises(RuntimeError, match="source-file limit"):
            execute_ingestion_job(
                session,
                job,
                settings,
                acquirer=FakeAcquirer(tmp_path),
                vector_store=RecordingVectorStore(),
            )

        session.refresh(job)
        assert job.status == IngestionJobStatus.FAILED
        assert job.error_message and "source-file limit" in job.error_message


def test_job_endpoint_deduplicates_active_jobs(client: TestClient) -> None:
    scheduled: list[str] = []

    def runner(job_id, settings) -> None:
        scheduled.append(str(job_id))

    app.dependency_overrides[get_ingestion_job_runner] = lambda: runner
    repository = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://github.com/example/background"},
    ).json()

    first = client.post(f"/api/v1/repositories/{repository['id']}/ingestion-jobs")
    second = client.post(f"/api/v1/repositories/{repository['id']}/ingestion-jobs")

    assert first.status_code == 202
    assert first.json()["status"] == "queued"
    assert second.json()["id"] == first.json()["id"]
    assert scheduled == [first.json()["id"]]


def test_job_endpoint_rejects_work_when_queue_is_full(client: TestClient) -> None:
    settings = Settings(_env_file=None, ingestion_max_queued_jobs=1)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ingestion_job_runner] = lambda: (lambda job_id, config: None)
    repositories = [
        client.post(
            "/api/v1/repositories",
            json={"github_url": f"https://github.com/example/queued-{index}"},
        ).json()
        for index in range(2)
    ]

    first = client.post(f"/api/v1/repositories/{repositories[0]['id']}/ingestion-jobs")
    second = client.post(f"/api/v1/repositories/{repositories[1]['id']}/ingestion-jobs")

    assert first.status_code == 202
    assert second.status_code == 503
    assert second.headers["Retry-After"] == "60"
    assert second.json()["error"]["message"] == "Ingestion queue is at capacity; retry later"
