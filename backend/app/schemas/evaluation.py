from datetime import datetime

from pydantic import BaseModel

from app.evaluation.report import (
    MetricSummary,
    ModelAssistedMetrics,
    RetrievalComparison,
    RetrievalConfigurationSummary,
)


class EvaluationResultSummary(BaseModel):
    generated_at: datetime
    dataset_id: str
    dataset_sha256: str
    embedding_provider: str
    embedding_dimensions: int
    configurations: list[str]
    k_values: list[int]
    retrieval_summaries: list[RetrievalConfigurationSummary]
    retrieval_comparisons: list[RetrievalComparison]
    routing_category: MetricSummary
    routing_strategy: MetricSummary
    symbol_lookup: MetricSummary
    tool_selection: MetricSummary
    unsupported_configurations: dict[str, str]
    model_assisted_metrics: ModelAssistedMetrics
