from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session
from app.retrieval.vector_store import QdrantVectorStore, VectorStoreError
from app.schemas.health import HealthResponse, LivenessResponse

router = APIRouter(tags=["health"])


def get_readiness_vector_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> QdrantVectorStore:
    return QdrantVectorStore(settings)


@router.get("/health/live", response_model=LivenessResponse)
def liveness_check() -> LivenessResponse:
    return LivenessResponse(status="ok")


def _readiness(
    session: Session,
    vector_store: QdrantVectorStore,
) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc
    try:
        vector_store.health_check()
    except VectorStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector database is unavailable",
        ) from exc
    return HealthResponse(status="ok", database="ok", vector_database="ok")


@router.get("/health", response_model=HealthResponse)
@router.get("/health/ready", response_model=HealthResponse)
def readiness_check(
    session: Annotated[Session, Depends(get_session)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_readiness_vector_store)],
) -> HealthResponse:
    return _readiness(session, vector_store)
