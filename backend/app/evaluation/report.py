from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceResult(ReportModel):
    rank: int
    filepath: str
    symbol_name: str | None
    qualified_name: str | None
    start_line: int
    end_line: int
    source_url: str
    semantic_score: float | None
    lexical_score: float | None
    hybrid_score: float | None


class RetrievalCaseResult(ReportModel):
    case_id: str
    repository: str
    commit: str
    question: str
    question_type: str
    configuration: str
    latency_ms: float
    recall_at_k: dict[str, float]
    citation_correctness_at_k: dict[str, float]
    evidence: list[EvidenceResult]


class LatencySummary(ReportModel):
    sample_count: int
    mean_ms: float | None
    median_ms: float | None
    p95_ms: float | None


class RetrievalConfigurationSummary(ReportModel):
    configuration: str
    case_count: int
    mean_recall_at_k: dict[str, float | None]
    mean_citation_correctness_at_k: dict[str, float | None]
    latency: LatencySummary


class RetrievalComparison(ReportModel):
    baseline: str
    contender: str
    recall_delta_at_k: dict[str, float | None]
    citation_correctness_delta_at_k: dict[str, float | None]


class RoutingCaseResult(ReportModel):
    case_id: str
    expected_category: str
    actual_category: str
    expected_strategy: str
    actual_strategy: str
    category_correct: bool
    strategy_correct: bool
    latency_ms: float


class SymbolLookupCaseResult(ReportModel):
    case_id: str
    query: str
    expected_symbols: list[str]
    returned_symbols: list[str]
    correct: bool
    latency_ms: float


class ToolSelectionCaseResult(ReportModel):
    case_id: str
    expected_tools: list[str]
    selected_tool: str | None
    measured: bool
    correct: bool | None


class MetricSummary(ReportModel):
    measured_cases: int
    accuracy: float | None
    latency: LatencySummary | None = None


class ModelAssistedMetrics(ReportModel):
    enabled: bool = False
    metrics: dict[str, float] = Field(default_factory=dict)
    note: str


class EvaluationReport(ReportModel):
    report_schema_version: int
    generated_at: datetime
    dataset_id: str
    dataset_schema_version: int
    dataset_sha256: str
    embedding_provider: str
    embedding_dimensions: int
    configurations: list[str]
    k_values: list[int]
    snapshot_ids: dict[str, str]
    retrieval_cases: list[RetrievalCaseResult]
    retrieval_summaries: list[RetrievalConfigurationSummary]
    retrieval_comparisons: list[RetrievalComparison]
    routing_cases: list[RoutingCaseResult]
    routing_category: MetricSummary
    routing_strategy: MetricSummary
    symbol_lookup_cases: list[SymbolLookupCaseResult]
    symbol_lookup: MetricSummary
    tool_selection_cases: list[ToolSelectionCaseResult]
    tool_selection: MetricSummary
    unsupported_configurations: dict[str, str]
    model_assisted_metrics: ModelAssistedMetrics
