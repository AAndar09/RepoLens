import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.code_symbol import SymbolKind
from app.models.retrieval import RetrievalIndexStatus

SearchMode = Literal["lexical", "semantic", "hybrid"]


class RetrievalIndexResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    status: RetrievalIndexStatus
    embedding_provider: str
    embedding_dimensions: int
    collection_name: str
    unit_count: int
    error_message: str | None
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    mode: SearchMode = "hybrid"
    limit: int = Field(default=10, ge=1, le=50)
    filepath: str | None = Field(default=None, max_length=1_024)
    filepath_prefix: str | None = Field(default=None, max_length=1_024)
    symbol_kind: SymbolKind | None = None
    language: str | None = Field(default="python", max_length=50)


class EvidenceResponse(BaseModel):
    retrieval_unit_id: uuid.UUID
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID
    commit_sha: str
    filepath: str
    language: str
    start_line: int
    end_line: int
    symbol_kind: SymbolKind | None
    symbol_name: str | None
    qualified_name: str | None
    content: str
    source_url: str
    semantic_score: float | None
    lexical_score: float | None
    hybrid_score: float | None


class SearchResponse(BaseModel):
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID
    commit_sha: str
    query: str
    mode: SearchMode
    results: list[EvidenceResponse]
