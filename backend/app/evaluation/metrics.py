import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from app.evaluation.dataset import EvaluationCase
from app.retrieval.service import RetrievalResult


def _symbol_matches(expected: str, result: RetrievalResult) -> bool:
    return expected in {result.unit.symbol_name, result.unit.qualified_name}


def result_is_relevant(case: EvaluationCase, result: RetrievalResult) -> bool:
    return result.unit.filepath in case.expected_files or any(
        _symbol_matches(expected, result) for expected in case.expected_symbols
    )


def retrieval_recall_at_k(
    case: EvaluationCase, results: Sequence[RetrievalResult], k: int
) -> float:
    expected_targets = {
        *(f"file:{filepath}" for filepath in case.expected_files),
        *(f"symbol:{symbol}" for symbol in case.expected_symbols),
    }
    if not expected_targets:
        raise ValueError("Recall@K requires at least one expected retrieval target")
    retrieved_targets: set[str] = set()
    for result in results[:k]:
        if result.unit.filepath in case.expected_files:
            retrieved_targets.add(f"file:{result.unit.filepath}")
        for expected in case.expected_symbols:
            if _symbol_matches(expected, result):
                retrieved_targets.add(f"symbol:{expected}")
    return len(expected_targets & retrieved_targets) / len(expected_targets)


def citation_correctness_at_k(
    case: EvaluationCase,
    results: Sequence[RetrievalResult],
    k: int,
    valid_line_counts: dict[str, int],
) -> float:
    selected = list(results[:k])
    if not selected:
        return 0.0
    correct = 0
    for result in selected:
        line_count = valid_line_counts.get(result.unit.filepath)
        traceable = (
            line_count is not None
            and 1 <= result.unit.start_line <= result.unit.end_line <= max(1, line_count)
        )
        if traceable and result_is_relevant(case, result):
            correct += 1
    return correct / len(selected)


@dataclass(frozen=True)
class LatencyMetrics:
    sample_count: int
    mean_ms: float | None
    median_ms: float | None
    p95_ms: float | None


def latency_metrics(values: Sequence[float]) -> LatencyMetrics:
    if not values:
        return LatencyMetrics(0, None, None, None)
    ordered = sorted(values)
    percentile_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return LatencyMetrics(
        sample_count=len(ordered),
        mean_ms=round(statistics.fmean(ordered), 3),
        median_ms=round(statistics.median(ordered), 3),
        p95_ms=round(ordered[percentile_index], 3),
    )


def mean_or_none(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 6) if values else None
