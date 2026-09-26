import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.code_symbol import SymbolKind
from app.models.snapshot import SnapshotStatus
from app.models.source_file import FileParseStatus


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    branch: str
    commit_sha: str
    status: SnapshotStatus
    error_message: str | None
    file_count: int
    parsed_file_count: int
    malformed_file_count: int
    skipped_file_count: int
    symbol_count: int
    import_count: int
    total_bytes: int
    created_at: datetime
    completed_at: datetime | None


class SourceFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    path: str
    module_name: str
    sha256: str
    size_bytes: int
    line_count: int
    parse_status: FileParseStatus
    parse_error: str | None


class SourceFileDetailResponse(SourceFileResponse):
    content: str


class SymbolResponse(BaseModel):
    id: uuid.UUID
    source_file_id: uuid.UUID
    file_path: str
    parent_id: uuid.UUID | None
    kind: SymbolKind
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    is_async: bool


class ImportResponse(BaseModel):
    id: uuid.UUID
    source_file_id: uuid.UUID
    file_path: str
    module: str
    imported_name: str | None
    alias: str | None
    level: int
    start_line: int
    end_line: int
