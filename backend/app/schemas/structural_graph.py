import uuid

from pydantic import BaseModel

from app.models.code_symbol import SymbolKind
from app.models.structural_graph import ImportResolutionStatus


class GraphSummaryResponse(BaseModel):
    snapshot_id: uuid.UUID
    module_count: int
    symbol_count: int
    import_count: int
    resolved_import_count: int
    unresolved_import_count: int
    ambiguous_import_count: int
    complete: bool


class ModuleNodeResponse(BaseModel):
    id: uuid.UUID
    path: str
    module_name: str


class GraphSymbolResponse(BaseModel):
    id: uuid.UUID
    source_file_id: uuid.UUID
    file_path: str
    parent_id: uuid.UUID | None
    kind: SymbolKind
    name: str
    qualified_name: str
    start_line: int
    end_line: int


class ImportRelationshipResponse(BaseModel):
    import_id: uuid.UUID
    source_module: ModuleNodeResponse
    target_module: ModuleNodeResponse | None
    status: ImportResolutionStatus
    requested_module: str
    resolved_module: str | None
    candidate_paths: list[str]
    reason: str
    start_line: int
    end_line: int


class SymbolContainmentResponse(BaseModel):
    symbol: GraphSymbolResponse
    parent: GraphSymbolResponse | None
    children: list[GraphSymbolResponse]
