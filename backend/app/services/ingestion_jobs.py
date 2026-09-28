import logging
import threading
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import get_engine
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.repository import Repository, RepositoryStatus
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider
from app.retrieval.service import RetrievalIndexer
from app.retrieval.vector_store import QdrantVectorStore, VectorStore
from app.services.ingestion import RepositoryAcquirer, RepositoryIngestionService

logger = logging.getLogger(__name__)
_semaphores: dict[int, threading.BoundedSemaphore] = {}
_semaphores_lock = threading.Lock()


def _semaphore(limit: int) -> threading.BoundedSemaphore:
    with _semaphores_lock:
        return _semaphores.setdefault(limit, threading.BoundedSemaphore(limit))


def execute_ingestion_job(
    session: Session,
    job: IngestionJob,
    settings: Settings,
    *,
    acquirer: RepositoryAcquirer | None = None,
    vector_store: VectorStore | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> IngestionJob:
    repository = session.get(Repository, job.repository_id)
    if repository is None:
        raise RuntimeError("Ingestion job repository no longer exists")
    job.status = IngestionJobStatus.RUNNING
    job.attempt_count += 1
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.error_message = None
    session.commit()
    try:
        snapshot = RepositoryIngestionService(session, settings, acquirer).ingest(repository)
        job = session.get(IngestionJob, job.id)
        if job is None:
            raise RuntimeError("Ingestion job disappeared during execution")
        job.snapshot_id = snapshot.id
        session.commit()
        RetrievalIndexer(
            session,
            settings,
            vector_store or QdrantVectorStore(settings),
            embedding_provider or create_embedding_provider(settings),
        ).index_snapshot(snapshot)
        job = session.get(IngestionJob, job.id)
        if job is None:
            raise RuntimeError("Ingestion job disappeared during indexing")
        job.status = IngestionJobStatus.SUCCEEDED
        job.completed_at = datetime.now(UTC)
        job.error_message = None
        session.commit()
        session.refresh(job)
        return job
    except Exception as exc:
        session.rollback()
        failed_job = session.get(IngestionJob, job.id)
        if failed_job is not None:
            failed_job.status = IngestionJobStatus.FAILED
            failed_job.error_message = (str(exc) or exc.__class__.__name__)[:2_000]
            failed_job.completed_at = datetime.now(UTC)
            session.commit()
        raise


def run_ingestion_job(job_id: uuid.UUID, settings: Settings) -> None:
    with _semaphore(settings.ingestion_max_concurrent_jobs):
        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        with factory() as session:
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != IngestionJobStatus.QUEUED:
                return
            try:
                execute_ingestion_job(session, job, settings)
                logger.info(
                    "ingestion_job_succeeded",
                    extra={
                        "event": "ingestion_job_succeeded",
                        "job_id": str(job_id),
                        "repository_id": str(job.repository_id),
                    },
                )
            except Exception as exc:
                logger.exception(
                    "ingestion_job_failed",
                    extra={
                        "event": "ingestion_job_failed",
                        "job_id": str(job_id),
                        "repository_id": str(job.repository_id),
                        "error_type": exc.__class__.__name__,
                    },
                )


def recover_interrupted_ingestion_jobs(session: Session) -> int:
    interrupted = list(
        session.scalars(
            select(IngestionJob).where(
                IngestionJob.status.in_(
                    [IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING]
                )
            )
        )
    )
    if not interrupted:
        return 0
    now = datetime.now(UTC)
    repository_ids = {item.repository_id for item in interrupted}
    for job in interrupted:
        job.status = IngestionJobStatus.FAILED
        job.error_message = "Worker stopped before the ingestion job completed; retry is safe"
        job.completed_at = now
    session.execute(
        update(Repository)
        .where(
            Repository.id.in_(repository_ids),
            Repository.status == RepositoryStatus.INGESTING,
        )
        .values(
            status=RepositoryStatus.FAILED,
            ingestion_error="Background ingestion was interrupted; retry the job",
        )
    )
    session.commit()
    return len(interrupted)
