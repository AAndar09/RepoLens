import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session
from app.graph.service import GraphEntityNotFoundError, StructuralGraphService
from app.models.code_symbol import CodeSymbol
from app.models.snapshot import RepositorySnapshot
from app.models.source_file import SourceFile
from app.models.structural_graph import ModuleImportResolution
from app.schemas.structural_graph import (
    GraphSummaryResponse,
    GraphSymbolResponse,
    ImportRelationshipResponse,
    ModuleNodeResponse,
    SymbolContainmentResponse,
)

router = APIRouter(prefix="/repositories", tags=["structural graph"])


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


def _service(session: Session, settings: Settings) -> StructuralGraphService:
    return StructuralGraphService(session, settings.graph_source_root_names)


def _module_response(source_file: SourceFile) -> ModuleNodeResponse:
    return ModuleNodeResponse(
        id=source_file.id,
        path=source_file.path,
        module_name=source_file.module_name,
    )


def _symbol_response(symbol: CodeSymbol, file_path: str) -> GraphSymbolResponse:
    return GraphSymbolResponse(
        id=symbol.id,
        source_file_id=symbol.source_file_id,
        file_path=file_path,
        parent_id=symbol.parent_id,
        kind=symbol.kind,
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
    )


def _import_response(resolution: ModuleImportResolution) -> ImportRelationshipResponse:
    source_import = resolution.source_import
    return ImportRelationshipResponse(
        import_id=source_import.id,
        source_module=_module_response(source_import.source_file),
        target_module=(
            _module_response(resolution.target_source_file)
            if resolution.target_source_file
            else None
        ),
        status=resolution.status,
        requested_module=resolution.requested_module,
        resolved_module=resolution.resolved_module,
        candidate_paths=resolution.candidate_paths,
        reason=resolution.reason,
        start_line=source_import.start_line,
        end_line=source_import.end_line,
    )


@router.post(
    "/{repository_id}/snapshots/{snapshot_id}/graph",
    response_model=GraphSummaryResponse,
)
def build_graph(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GraphSummaryResponse:
    snapshot = _snapshot_or_404(session, repository_id, snapshot_id)
    return GraphSummaryResponse.model_validate(
        _service(session, settings).build(snapshot), from_attributes=True
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/graph",
    response_model=GraphSummaryResponse,
)
def get_graph(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GraphSummaryResponse:
    snapshot = _snapshot_or_404(session, repository_id, snapshot_id)
    return GraphSummaryResponse.model_validate(
        _service(session, settings).summary(snapshot), from_attributes=True
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/graph/modules/{module_id}/symbols",
    response_model=list[GraphSymbolResponse],
)
def module_symbols(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    module_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GraphSymbolResponse]:
    _snapshot_or_404(session, repository_id, snapshot_id)
    try:
        source_file = _service(session, settings).module(snapshot_id, module_id)
        symbols = _service(session, settings).symbols_in_module(snapshot_id, module_id)
    except GraphEntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    selected_symbols = symbols[offset : offset + limit]
    return [_symbol_response(symbol, source_file.path) for symbol in selected_symbols]


def _module_relationships(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    module_id: uuid.UUID,
    session: Session,
    settings: Settings,
    *,
    incoming: bool,
    limit: int,
    offset: int,
) -> list[ImportRelationshipResponse]:
    _snapshot_or_404(session, repository_id, snapshot_id)
    service = _service(session, settings)
    try:
        relationships = (
            service.module_importers(snapshot_id, module_id)
            if incoming
            else service.module_imports(snapshot_id, module_id)
        )
    except GraphEntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    selected = relationships[offset : offset + limit]
    return [_import_response(item) for item in selected]


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/graph/modules/{module_id}/imports",
    response_model=list[ImportRelationshipResponse],
)
def module_imports(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    module_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ImportRelationshipResponse]:
    return _module_relationships(
        repository_id,
        snapshot_id,
        module_id,
        session,
        settings,
        incoming=False,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/graph/modules/{module_id}/importers",
    response_model=list[ImportRelationshipResponse],
)
def module_importers(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    module_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ImportRelationshipResponse]:
    return _module_relationships(
        repository_id,
        snapshot_id,
        module_id,
        session,
        settings,
        incoming=True,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/graph/symbols/{symbol_id}/containment",
    response_model=SymbolContainmentResponse,
)
def symbol_containment(
    repository_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    symbol_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    child_limit: Annotated[int, Query(ge=1, le=500)] = 100,
    child_offset: Annotated[int, Query(ge=0)] = 0,
) -> SymbolContainmentResponse:
    _snapshot_or_404(session, repository_id, snapshot_id)
    try:
        result = _service(session, settings).symbol_containment(snapshot_id, symbol_id)
    except GraphEntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SymbolContainmentResponse(
        symbol=_symbol_response(result.symbol, result.source_file.path),
        parent=(
            _symbol_response(result.parent, result.source_file.path) if result.parent else None
        ),
        children=[
            _symbol_response(child, result.source_file.path)
            for child in result.children[child_offset : child_offset + child_limit]
        ],
    )
