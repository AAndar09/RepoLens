import uuid
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session
from app.models.code_symbol import CodeSymbol, SymbolKind
from app.models.repository import Repository
from app.models.retrieval import SnapshotRetrievalIndex
from app.models.snapshot import RepositorySnapshot
from app.models.source_file import SourceFile
from app.models.source_import import SourceImport
from app.retrieval.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    create_embedding_provider,
)
from app.retrieval.service import (
    HybridRetriever,
    RetrievalFilters,
    RetrievalIndexer,
    RetrievalNotReadyError,
    RetrievalUnitLimitError,
)
from app.retrieval.vector_store import QdrantVectorStore, VectorStore, VectorStoreError
from app.schemas.ingestion import (
    ImportResponse,
    SnapshotResponse,
    SourceFileDetailResponse,
    SourceFileResponse,
    SymbolResponse,
)
from app.schemas.repository import RepositoryResponse, RepositorySubmission
from app.schemas.retrieval import (
    EvidenceResponse,
    RetrievalIndexResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.acquisition import (
    GitRepositoryAcquirer,
    RepositoryAcquisitionError,
    RepositoryCloneLimitError,
)
from app.services.ingestion import (
    IngestionResourceLimitError,
    RepositoryAcquirer,
    RepositoryIngestionService,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


def get_repository_acquirer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RepositoryAcquirer:
    return GitRepositoryAcquirer(
        timeout_seconds=settings.ingestion_clone_timeout_seconds,
        max_clone_bytes=settings.ingestion_max_clone_bytes,
    )


def get_vector_store(settings: Annotated[Settings, Depends(get_settings)]) -> VectorStore:
    return QdrantVectorStore(settings)


def get_embedding_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmbeddingProvider:
    return create_embedding_provider(settings)


def _repository_or_404(session: Session, repository_id: uuid.UUID) -> Repository:
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    return repository


def _snapshot_or_404(
    session: Session, repository_id: uuid.UUID, snapshot_id: uuid.UUID
) -> RepositorySnapshot:
    snapshot = session.scalar(
        select(RepositorySnapshot).where(
            RepositorySnapshot.id == snapshot_id,
            RepositorySnapshot.repository_id == repository_id,
        )
    )
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return snapshot


def _retrieval_index_or_404(session: Session, snapshot_id: uuid.UUID) -> SnapshotRetrievalIndex:
    retrieval_index = session.scalar(
        select(SnapshotRetrievalIndex).where(SnapshotRetrievalIndex.snapshot_id == snapshot_id)
    )
    if retrieval_index is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retrieval index not found",
        )
    return retrieval_index


@router.post("", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
def submit_repository(
    submission: RepositorySubmission,
    session: Annotated[Session, Depends(get_session)],
) -> Repository:
    owner, name = urlsplit(submission.github_url).path.strip("/").split("/")
    existing = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == name)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository has already been submitted",
        )

    repository = Repository(github_url=submission.github_url, owner=owner, name=name)
    session.add(repository)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository has already been submitted",
        ) from exc
    session.refresh(repository)
    return repository


@router.get("/{repository_id}", response_model=RepositoryResponse)
def get_repository(
    repository_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> Repository:
    return _repository_or_404(session, repository_id)


@router.post("/{repository_id}/ingestions", response_model=SnapshotResponse)
def ingest_repository(
    repository_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    acquirer: Annotated[RepositoryAcquirer, Depends(get_repository_acquirer)],
) -> RepositorySnapshot:
    repository = _repository_or_404(session, repository_id)
    service = RepositoryIngestionService(session, settings, acquirer)
    try:
        return service.ingest(repository)
    except (IngestionResourceLimitError, RepositoryCloneLimitError) as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except RepositoryAcquisitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Repository could not be acquired: {exc}",
        ) from exc


@router.get("/{repository_id}/snapshots", response_model=list[SnapshotResponse])
def list_snapshots(
    repository_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RepositorySnapshot]:
    _repository_or_404(session, repository_id)
    return list(
        session.scalars(
            select(RepositorySnapshot)
            .where(RepositorySnapshot.repository_id == repository_id)
            .order_by(RepositorySnapshot.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/files", response_model=list[SourceFileResponse]
)
def list_files(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SourceFile]:
    _snapshot_or_404(session, repository_id, snapshot_id)
    return list(
        session.scalars(
            select(SourceFile)
            .where(SourceFile.snapshot_id == snapshot_id)
            .order_by(SourceFile.path)
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/files/{file_id}",
    response_model=SourceFileDetailResponse,
)
def get_file(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    file_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> SourceFile:
    _snapshot_or_404(session, repository_id, snapshot_id)
    source_file = session.scalar(
        select(SourceFile).where(SourceFile.id == file_id, SourceFile.snapshot_id == snapshot_id)
    )
    if source_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source file not found")
    return source_file


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/symbols", response_model=list[SymbolResponse]
)
def list_symbols(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    kind: SymbolKind | None = None,
    name: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SymbolResponse]:
    _snapshot_or_404(session, repository_id, snapshot_id)
    query = (
        select(CodeSymbol, SourceFile.path)
        .join(SourceFile, SourceFile.id == CodeSymbol.source_file_id)
        .where(SourceFile.snapshot_id == snapshot_id)
        .order_by(SourceFile.path, CodeSymbol.start_line)
    )
    if kind is not None:
        query = query.where(CodeSymbol.kind == kind)
    if name:
        query = query.where(CodeSymbol.name == name)
    rows = session.execute(query.offset(offset).limit(limit)).all()
    return [
        SymbolResponse(
            id=symbol.id,
            source_file_id=symbol.source_file_id,
            file_path=file_path,
            parent_id=symbol.parent_id,
            kind=symbol.kind,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            is_async=symbol.is_async,
        )
        for symbol, file_path in rows
    ]


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/imports", response_model=list[ImportResponse]
)
def list_imports(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ImportResponse]:
    _snapshot_or_404(session, repository_id, snapshot_id)
    rows = session.execute(
        select(SourceImport, SourceFile.path)
        .join(SourceFile, SourceFile.id == SourceImport.source_file_id)
        .where(SourceFile.snapshot_id == snapshot_id)
        .order_by(SourceFile.path, SourceImport.start_line)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        ImportResponse(
            id=source_import.id,
            source_file_id=source_import.source_file_id,
            file_path=file_path,
            module=source_import.module,
            imported_name=source_import.imported_name,
            alias=source_import.alias,
            level=source_import.level,
            start_line=source_import.start_line,
            end_line=source_import.end_line,
        )
        for source_import, file_path in rows
    ]


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/retrieval-index",
    response_model=RetrievalIndexResponse,
)
def get_retrieval_index(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> SnapshotRetrievalIndex:
    _snapshot_or_404(session, repository_id, snapshot_id)
    return _retrieval_index_or_404(session, snapshot_id)


@router.post(
    "/{repository_id}/snapshots/{snapshot_id}/retrieval-index",
    response_model=RetrievalIndexResponse,
)
def index_snapshot_for_retrieval(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    refresh: bool = False,
) -> SnapshotRetrievalIndex:
    snapshot = _snapshot_or_404(session, repository_id, snapshot_id)
    try:
        return RetrievalIndexer(session, settings, vector_store, embedding_provider).index_snapshot(
            snapshot,
            refresh=refresh,
        )
    except RetrievalUnitLimitError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except EmbeddingConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except VectorStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _evidence_response(
    repository: Repository,
    snapshot: RepositorySnapshot,
    result,
) -> EvidenceResponse:
    unit = result.unit
    fragment = f"#L{unit.start_line}"
    if unit.end_line != unit.start_line:
        fragment = f"{fragment}-L{unit.end_line}"
    source_url = (
        f"https://github.com/{repository.owner}/{repository.name}/blob/{snapshot.commit_sha}/"
        f"{quote(unit.filepath, safe='/')}{fragment}"
    )
    return EvidenceResponse(
        retrieval_unit_id=unit.id,
        repository_id=repository.id,
        snapshot_id=snapshot.id,
        commit_sha=snapshot.commit_sha,
        filepath=unit.filepath,
        language=unit.language,
        start_line=unit.start_line,
        end_line=unit.end_line,
        symbol_kind=unit.symbol_kind,
        symbol_name=unit.symbol_name,
        qualified_name=unit.qualified_name,
        content=unit.content,
        source_url=source_url,
        semantic_score=result.semantic_score,
        lexical_score=result.lexical_score,
        hybrid_score=result.hybrid_score,
    )


@router.post(
    "/{repository_id}/snapshots/{snapshot_id}/search",
    response_model=SearchResponse,
)
def search_snapshot(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: SearchRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> SearchResponse:
    repository = _repository_or_404(session, repository_id)
    snapshot = _snapshot_or_404(session, repository_id, snapshot_id)
    try:
        results = HybridRetriever(session, settings, vector_store, embedding_provider).search(
            repository,
            snapshot,
            request.query,
            request.mode,
            RetrievalFilters(
                filepath=request.filepath,
                filepath_prefix=request.filepath_prefix,
                symbol_kind=request.symbol_kind,
                language=request.language,
            ),
            request.limit,
        )
    except RetrievalNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (EmbeddingConfigurationError, VectorStoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return SearchResponse(
        repository_id=repository.id,
        snapshot_id=snapshot.id,
        commit_sha=snapshot.commit_sha,
        query=request.query,
        mode=request.mode,
        results=[_evidence_response(repository, snapshot, result) for result in results],
    )
