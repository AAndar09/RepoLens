import time
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.tools import ControlledToolset
from app.config import Settings
from app.evaluation.dataset import EvaluationCase, EvaluationDataset, RepositoryCases
from app.evaluation.metrics import (
    citation_correctness_at_k,
    latency_metrics,
    mean_or_none,
    retrieval_recall_at_k,
)
from app.evaluation.report import (
    EvaluationReport,
    EvidenceResult,
    LatencySummary,
    MetricSummary,
    ModelAssistedMetrics,
    RetrievalCaseResult,
    RetrievalComparison,
    RetrievalConfigurationSummary,
    RoutingCaseResult,
    SymbolLookupCaseResult,
    ToolSelectionCaseResult,
)
from app.models.repository import Repository
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.models.source_file import SourceFile
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.service import HybridRetriever, RetrievalFilters
from app.retrieval.vector_store import VectorStore
from app.routing.service import RouteStrategy, RuleBasedQueryClassifier
from app.schemas.investigation import ToolRequest

SUPPORTED_CONFIGURATIONS = frozenset({"lexical", "semantic", "hybrid"})


class EvaluationError(RuntimeError):
    pass


class EvaluationRunner:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider

    def _resolve_snapshot(
        self, repository_cases: RepositoryCases
    ) -> tuple[Repository, RepositorySnapshot]:
        owner, name = repository_cases.owner_and_name
        row = self.session.execute(
            select(Repository, RepositorySnapshot)
            .join(RepositorySnapshot, RepositorySnapshot.repository_id == Repository.id)
            .where(
                func.lower(Repository.owner) == owner.lower(),
                func.lower(Repository.name) == name.lower(),
                RepositorySnapshot.commit_sha == repository_cases.commit,
            )
        ).one_or_none()
        if row is None:
            raise EvaluationError(
                f"Dataset snapshot {owner}/{name}@{repository_cases.commit} is not ingested"
            )
        repository, snapshot = row
        if snapshot.status != SnapshotStatus.READY:
            raise EvaluationError(
                f"Dataset snapshot {owner}/{name}@{repository_cases.commit} is not ready"
            )
        return repository, snapshot

    def _source_line_counts(self, snapshot: RepositorySnapshot) -> dict[str, int]:
        return dict(
            self.session.execute(
                select(SourceFile.path, SourceFile.line_count).where(
                    SourceFile.snapshot_id == snapshot.id
                )
            ).all()
        )

    @staticmethod
    def _source_url(
        repository: Repository,
        snapshot: RepositorySnapshot,
        filepath: str,
        start_line: int,
        end_line: int,
    ) -> str:
        fragment = f"#L{start_line}"
        if end_line != start_line:
            fragment += f"-L{end_line}"
        return (
            f"https://github.com/{repository.owner}/{repository.name}/blob/"
            f"{snapshot.commit_sha}/{quote(filepath, safe='/')}{fragment}"
        )

    def _evaluate_retrieval_case(
        self,
        repository_cases: RepositoryCases,
        case: EvaluationCase,
        repository: Repository,
        snapshot: RepositorySnapshot,
        configuration: str,
        k_values: tuple[int, ...],
        line_counts: dict[str, int],
    ) -> RetrievalCaseResult:
        started = time.perf_counter()
        results = HybridRetriever(
            self.session,
            self.settings,
            self.vector_store,
            self.embedding_provider,
        ).search(
            repository,
            snapshot,
            case.question,
            configuration,
            RetrievalFilters(language="python"),
            max(k_values),
        )
        latency_ms = (time.perf_counter() - started) * 1_000
        evidence = [
            EvidenceResult(
                rank=rank,
                filepath=result.unit.filepath,
                symbol_name=result.unit.symbol_name,
                qualified_name=result.unit.qualified_name,
                start_line=result.unit.start_line,
                end_line=result.unit.end_line,
                source_url=self._source_url(
                    repository,
                    snapshot,
                    result.unit.filepath,
                    result.unit.start_line,
                    result.unit.end_line,
                ),
                semantic_score=result.semantic_score,
                lexical_score=result.lexical_score,
                hybrid_score=result.hybrid_score,
            )
            for rank, result in enumerate(results, start=1)
        ]
        return RetrievalCaseResult(
            case_id=case.id,
            repository=repository_cases.repository,
            commit=repository_cases.commit,
            question=case.question,
            question_type=case.question_type,
            configuration=configuration,
            latency_ms=round(latency_ms, 3),
            recall_at_k={
                str(k): round(retrieval_recall_at_k(case, results, k), 6) for k in k_values
            },
            citation_correctness_at_k={
                str(k): round(citation_correctness_at_k(case, results, k, line_counts), 6)
                for k in k_values
            },
            evidence=evidence,
        )

    @staticmethod
    def _selected_direct_tool(strategy: RouteStrategy) -> str | None:
        return {
            RouteStrategy.REPOSITORY_METADATA: "repository_metadata",
            RouteStrategy.DIRECT_SYMBOL_LOOKUP: "lookup_symbol",
            RouteStrategy.HYBRID_RETRIEVAL: "search_code",
        }.get(strategy)

    def _evaluate_non_retrieval_metrics(
        self,
        repository_cases: RepositoryCases,
        repository: Repository,
        snapshot: RepositorySnapshot,
    ) -> tuple[
        list[RoutingCaseResult],
        list[SymbolLookupCaseResult],
        list[ToolSelectionCaseResult],
    ]:
        routing_results: list[RoutingCaseResult] = []
        symbol_results: list[SymbolLookupCaseResult] = []
        tool_results: list[ToolSelectionCaseResult] = []
        tools = ControlledToolset(
            self.session,
            self.settings,
            repository,
            snapshot,
            self.vector_store,
            self.embedding_provider,
        )
        classifier = RuleBasedQueryClassifier()
        for case in repository_cases.cases:
            started = time.perf_counter()
            decision = classifier.classify(case.question)
            routing_latency = (time.perf_counter() - started) * 1_000
            if case.expected_routing is not None:
                routing_results.append(
                    RoutingCaseResult(
                        case_id=case.id,
                        expected_category=case.expected_routing.category.value,
                        actual_category=decision.category.value,
                        expected_strategy=case.expected_routing.strategy.value,
                        actual_strategy=decision.strategy.value,
                        category_correct=(
                            decision.category is case.expected_routing.category
                        ),
                        strategy_correct=(
                            decision.strategy is case.expected_routing.strategy
                        ),
                        latency_ms=round(routing_latency, 3),
                    )
                )
            if case.expected_tools:
                selected_tool = self._selected_direct_tool(decision.strategy)
                measured = selected_tool is not None
                tool_results.append(
                    ToolSelectionCaseResult(
                        case_id=case.id,
                        expected_tools=list(case.expected_tools),
                        selected_tool=selected_tool,
                        measured=measured,
                        correct=(selected_tool in case.expected_tools) if measured else None,
                    )
                )
            if case.symbol_query:
                started = time.perf_counter()
                result = tools.execute(
                    ToolRequest(
                        tool="lookup_symbol",
                        arguments={"name": case.symbol_query, "limit": 50},
                        purpose="Evaluate deterministic symbol lookup",
                    )
                )
                lookup_latency = (time.perf_counter() - started) * 1_000
                returned_names = {
                    str(value)
                    for item in result.evidence
                    for key in ("name", "qualified_name")
                    if (value := item.data.get(key)) is not None
                }
                returned_symbols = sorted(
                    str(item.data["qualified_name"])
                    for item in result.evidence
                    if item.data.get("qualified_name") is not None
                )
                symbol_results.append(
                    SymbolLookupCaseResult(
                        case_id=case.id,
                        query=case.symbol_query,
                        expected_symbols=case.expected_symbols,
                        returned_symbols=returned_symbols,
                        correct=all(
                            expected in returned_names for expected in case.expected_symbols
                        ),
                        latency_ms=round(lookup_latency, 3),
                    )
                )
        return routing_results, symbol_results, tool_results

    @staticmethod
    def _latency_summary(values: list[float]) -> LatencySummary:
        return LatencySummary.model_validate(latency_metrics(values).__dict__)

    def _retrieval_summaries(
        self,
        results: list[RetrievalCaseResult],
        configurations: tuple[str, ...],
        k_values: tuple[int, ...],
    ) -> list[RetrievalConfigurationSummary]:
        summaries = []
        for configuration in configurations:
            selected = [item for item in results if item.configuration == configuration]
            summaries.append(
                RetrievalConfigurationSummary(
                    configuration=configuration,
                    case_count=len(selected),
                    mean_recall_at_k={
                        str(k): mean_or_none([item.recall_at_k[str(k)] for item in selected])
                        for k in k_values
                    },
                    mean_citation_correctness_at_k={
                        str(k): mean_or_none(
                            [item.citation_correctness_at_k[str(k)] for item in selected]
                        )
                        for k in k_values
                    },
                    latency=self._latency_summary([item.latency_ms for item in selected]),
                )
            )
        return summaries

    @staticmethod
    def _comparisons(
        summaries: list[RetrievalConfigurationSummary],
        k_values: tuple[int, ...],
    ) -> list[RetrievalComparison]:
        if len(summaries) < 2:
            return []
        baseline = summaries[0]
        comparisons = []
        for contender in summaries[1:]:
            recall_delta: dict[str, float | None] = {}
            citation_delta: dict[str, float | None] = {}
            for k in k_values:
                key = str(k)
                baseline_recall = baseline.mean_recall_at_k[key]
                contender_recall = contender.mean_recall_at_k[key]
                baseline_citation = baseline.mean_citation_correctness_at_k[key]
                contender_citation = contender.mean_citation_correctness_at_k[key]
                recall_delta[key] = (
                    round(contender_recall - baseline_recall, 6)
                    if baseline_recall is not None and contender_recall is not None
                    else None
                )
                citation_delta[key] = (
                    round(contender_citation - baseline_citation, 6)
                    if baseline_citation is not None and contender_citation is not None
                    else None
                )
            comparisons.append(
                RetrievalComparison(
                    baseline=baseline.configuration,
                    contender=contender.configuration,
                    recall_delta_at_k=recall_delta,
                    citation_correctness_delta_at_k=citation_delta,
                )
            )
        return comparisons

    @staticmethod
    def _accuracy_summary(
        values: list[bool], latencies: list[float] | None = None
    ) -> MetricSummary:
        return MetricSummary(
            measured_cases=len(values),
            accuracy=mean_or_none([float(value) for value in values]),
            latency=(
                EvaluationRunner._latency_summary(latencies)
                if latencies is not None
                else None
            ),
        )

    def run(
        self,
        dataset: EvaluationDataset,
        dataset_sha256: str,
        *,
        configurations: tuple[str, ...] = ("semantic", "hybrid"),
        k_values: tuple[int, ...] = (1, 3, 5),
    ) -> EvaluationReport:
        if not configurations or any(
            configuration not in SUPPORTED_CONFIGURATIONS
            for configuration in configurations
        ):
            raise EvaluationError(
                "Configurations must be one or more of lexical, semantic, hybrid"
            )
        if not k_values or any(k < 1 for k in k_values) or len(k_values) != len(set(k_values)):
            raise EvaluationError("K values must be unique positive integers")
        configurations = tuple(dict.fromkeys(configurations))
        k_values = tuple(sorted(k_values))

        retrieval_results: list[RetrievalCaseResult] = []
        routing_results: list[RoutingCaseResult] = []
        symbol_results: list[SymbolLookupCaseResult] = []
        tool_results: list[ToolSelectionCaseResult] = []
        snapshot_ids: dict[str, str] = {}

        for repository_cases in dataset.repositories:
            repository, snapshot = self._resolve_snapshot(repository_cases)
            snapshot_key = f"{repository.owner}/{repository.name}@{snapshot.commit_sha}"
            snapshot_ids[snapshot_key] = str(snapshot.id)
            line_counts = self._source_line_counts(snapshot)
            for case in repository_cases.cases:
                if not case.retrieval:
                    continue
                for configuration in configurations:
                    retrieval_results.append(
                        self._evaluate_retrieval_case(
                            repository_cases,
                            case,
                            repository,
                            snapshot,
                            configuration,
                            k_values,
                            line_counts,
                        )
                    )
            routing, symbols, tools = self._evaluate_non_retrieval_metrics(
                repository_cases, repository, snapshot
            )
            routing_results.extend(routing)
            symbol_results.extend(symbols)
            tool_results.extend(tools)

        summaries = self._retrieval_summaries(
            retrieval_results, configurations, k_values
        )
        measured_tools = [item for item in tool_results if item.measured]
        return EvaluationReport(
            report_schema_version=1,
            generated_at=datetime.now(UTC),
            dataset_id=dataset.dataset_id,
            dataset_schema_version=dataset.schema_version,
            dataset_sha256=dataset_sha256,
            embedding_provider=self.embedding_provider.name,
            embedding_dimensions=self.embedding_provider.dimensions,
            configurations=list(configurations),
            k_values=list(k_values),
            snapshot_ids=snapshot_ids,
            retrieval_cases=retrieval_results,
            retrieval_summaries=summaries,
            retrieval_comparisons=self._comparisons(summaries, k_values),
            routing_cases=routing_results,
            routing_category=self._accuracy_summary(
                [item.category_correct for item in routing_results],
                [item.latency_ms for item in routing_results],
            ),
            routing_strategy=self._accuracy_summary(
                [item.strategy_correct for item in routing_results],
                [item.latency_ms for item in routing_results],
            ),
            symbol_lookup_cases=symbol_results,
            symbol_lookup=self._accuracy_summary(
                [item.correct for item in symbol_results],
                [item.latency_ms for item in symbol_results],
            ),
            tool_selection_cases=tool_results,
            tool_selection=self._accuracy_summary(
                [bool(item.correct) for item in measured_tools]
            ),
            unsupported_configurations={
                "hybrid_structural": (
                    "Structural graph lookup is a separate controlled tool, not a retrieval "
                    "ranking configuration in the current architecture."
                ),
                "reranked": "No production reranker is currently implemented.",
            },
            model_assisted_metrics=ModelAssistedMetrics(
                note=(
                    "Disabled. This report contains deterministic retrieval, citation-metadata, "
                    "routing, symbol, and direct tool-selection metrics only."
                )
            ),
        )
