import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.model import (
    InvestigationModel,
    InvestigationModelConfigurationError,
    InvestigationModelError,
    create_investigation_model,
)
from app.agent.tools import ControlledToolset
from app.agent.workflow import (
    AgentOutputValidationError,
    AgentStepLimitError,
    InvestigationAgent,
)
from app.api.routes.repositories import get_embedding_provider, get_vector_store
from app.config import Settings, get_settings
from app.database import get_session
from app.models.repository import Repository
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.vector_store import VectorStore
from app.routing.execution import RoutedQueryService
from app.routing.service import LayaQueryClassifier, RouteStrategy
from app.schemas.investigation import (
    InvestigationRequest,
    InvestigationResponse,
    RoutedQueryRequest,
    RoutedQueryResponse,
)

router = APIRouter(prefix="/repositories", tags=["investigations"])


def get_investigation_model(
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvestigationModel:
    try:
        return create_investigation_model(settings)
    except InvestigationModelConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/{repository_id}/snapshots/{snapshot_id}/investigations",
    response_model=InvestigationResponse,
)
def investigate_repository(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: InvestigationRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    model: Annotated[InvestigationModel, Depends(get_investigation_model)],
) -> InvestigationResponse:
    row = session.execute(
        select(Repository, RepositorySnapshot)
        .join(RepositorySnapshot, RepositorySnapshot.repository_id == Repository.id)
        .where(
            Repository.id == repository_id,
            RepositorySnapshot.id == snapshot_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    repository, snapshot = row
    if snapshot.status != SnapshotStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only ready snapshots can be investigated",
        )
    tools = ControlledToolset(
        session,
        settings,
        repository,
        snapshot,
        vector_store,
        embedding_provider,
    )
    try:
        return InvestigationAgent(settings, model, tools).investigate(request.question)
    except InvestigationModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except AgentOutputValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Investigation model returned invalid output: {exc}",
        ) from exc
    except AgentStepLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post(
    "/{repository_id}/snapshots/{snapshot_id}/queries",
    response_model=RoutedQueryResponse,
)
def route_repository_query(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: RoutedQueryRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> RoutedQueryResponse:
    row = session.execute(
        select(Repository, RepositorySnapshot)
        .join(RepositorySnapshot, RepositorySnapshot.repository_id == Repository.id)
        .where(Repository.id == repository_id, RepositorySnapshot.id == snapshot_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    repository, snapshot = row
    if snapshot.status != SnapshotStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only ready snapshots can be queried",
        )
    decision = LayaQueryClassifier(settings).classify(request.question)
    tools = ControlledToolset(
        session, settings, repository, snapshot, vector_store, embedding_provider
    )
    try:
        model = None
        if decision.strategy is RouteStrategy.FULL_INVESTIGATION:
            model = get_investigation_model(settings)
        return RoutedQueryService(settings, tools).execute(request.question, decision, model)
    except InvestigationModelError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AgentOutputValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Investigation model returned invalid output: {exc}",
        ) from exc
    except AgentStepLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
