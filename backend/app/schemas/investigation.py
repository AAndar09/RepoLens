import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.code_symbol import SymbolKind

ToolName = Literal[
    "search_code",
    "lookup_symbol",
    "read_source",
    "structural_lookup",
    "repository_metadata",
    "list_dependencies",
    "check_vulnerabilities",
]
TerminationReason = Literal["completed", "max_steps", "no_more_tools"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolRequest(StrictModel):
    tool: ToolName
    arguments: dict[str, object] = Field(default_factory=dict)
    purpose: str = Field(min_length=1, max_length=500)


class InvestigationPlan(StrictModel):
    objective: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    tool_calls: list[ToolRequest] = Field(min_length=1, max_length=10)


class SufficiencyDecision(StrictModel):
    sufficient: bool
    reasoning: str = Field(min_length=1, max_length=2_000)
    additional_tool_calls: list[ToolRequest] = Field(default_factory=list, max_length=10)


class AnswerDraft(StrictModel):
    answer: str = Field(min_length=1, max_length=20_000)
    citation_ids: list[str] = Field(default_factory=list, max_length=50)


class SearchCodeArguments(StrictModel):
    query: str = Field(min_length=1, max_length=2_000)
    mode: Literal["semantic", "hybrid"] = "hybrid"
    limit: int = Field(default=5, ge=1, le=10)
    filepath: str | None = Field(default=None, max_length=1_024)
    filepath_prefix: str | None = Field(default=None, max_length=1_024)
    symbol_kind: SymbolKind | None = None


class LookupSymbolArguments(StrictModel):
    name: str = Field(min_length=1, max_length=2_048)
    kind: SymbolKind | None = None
    limit: int = Field(default=10, ge=1, le=50)


class ReadSourceArguments(StrictModel):
    filepath: str = Field(min_length=1, max_length=1_024)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class StructuralLookupArguments(StrictModel):
    operation: Literal[
        "module_symbols",
        "module_imports",
        "module_importers",
        "symbol_containment",
    ]
    entity_id: uuid.UUID
    limit: int = Field(default=20, ge=1, le=50)


class RepositoryMetadataArguments(StrictModel):
    pass


class ListDependenciesArguments(StrictModel):
    package: str | None = Field(default=None, max_length=255)
    resolved_only: bool = False
    limit: int = Field(default=50, ge=1, le=100)


class CheckVulnerabilitiesArguments(StrictModel):
    package: str | None = Field(default=None, max_length=255)
    refresh: bool = False
    limit: int = Field(default=50, ge=1, le=100)


class CitationResponse(StrictModel):
    id: str
    snapshot_id: uuid.UUID
    commit_sha: str
    filepath: str
    start_line: int
    end_line: int
    source_url: str
    title: str
    excerpt: str


class ToolTraceResponse(StrictModel):
    call_id: str
    step: int
    tool: ToolName
    arguments: dict[str, object]
    purpose: str
    status: Literal["success", "error"]
    summary: str | None = None
    error: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class InvestigationRequest(StrictModel):
    question: str = Field(min_length=3, max_length=2_000)


class InvestigationResponse(StrictModel):
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID
    commit_sha: str
    question: str
    plan: InvestigationPlan
    answer: str
    citations: list[CitationResponse]
    tool_trace: list[ToolTraceResponse]
    steps_taken: int
    termination_reason: TerminationReason


class RoutedQueryRequest(StrictModel):
    question: str = Field(min_length=3, max_length=2_000)


class RoutedQueryResponse(StrictModel):
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID
    commit_sha: str
    question: str
    routing: dict[str, object]
    answer: str
    citations: list[CitationResponse] = Field(default_factory=list)
    tool_trace: list[ToolTraceResponse] = Field(default_factory=list)
    investigation: InvestigationResponse | None = None
