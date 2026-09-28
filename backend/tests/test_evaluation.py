import hashlib
import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings
from app.evaluation.dataset import EvaluationDataset, load_dataset
from app.evaluation.runner import EvaluationError, EvaluationRunner
from app.models.code_symbol import CodeSymbol, SymbolKind
from app.models.repository import Repository
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.models.source_file import FileParseStatus, SourceFile
from app.retrieval.service import RetrievalIndexer
from app.retrieval.vector_store import VectorHit, VectorPoint


class EvaluationEmbeddings:
    name = "evaluation-test"
    dimensions = 16

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0] + [0.0] * 14
            if "auth" in text.lower() or "sign in" in text.lower()
            else [0.0, 1.0] + [0.0] * 14
            for text in texts
        ]


class EvaluationVectors:
    def __init__(self) -> None:
        self.points: dict[uuid.UUID, list[VectorPoint]] = {}

    def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        del collection_name, dimensions

    def replace_snapshot(
        self, collection_name: str, snapshot_id: uuid.UUID, points: list[VectorPoint]
    ) -> None:
        del collection_name
        self.points[snapshot_id] = points

    def search(
        self,
        collection_name: str,
        vector: list[float],
        snapshot_id: uuid.UUID,
        limit: int,
        filepath: str | None = None,
        symbol_kind: str | None = None,
        language: str | None = None,
    ) -> list[VectorHit]:
        del collection_name
        hits: list[VectorHit] = []
        for point in self.points.get(snapshot_id, []):
            if filepath and point.payload["filepath"] != filepath:
                continue
            if symbol_kind and point.payload["symbol_kind"] != symbol_kind:
                continue
            if language and point.payload["language"] != language:
                continue
            score = sum(left * right for left, right in zip(vector, point.vector, strict=True))
            hits.append(VectorHit(point.id, score))
        return sorted(hits, key=lambda item: (-item.score, str(item.id)))[:limit]


def _source(snapshot: RepositorySnapshot, path: str, content: str) -> SourceFile:
    return SourceFile(
        snapshot=snapshot,
        path=path,
        module_name=path.removesuffix(".py").replace("/", "."),
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content),
        line_count=len(content.splitlines()),
        parse_status=FileParseStatus.PARSED,
        content=content,
    )


def _seed(session: Session) -> tuple[Repository, RepositorySnapshot]:
    repository = Repository(github_url="https://github.com/acme/demo", owner="acme", name="demo")
    snapshot = RepositorySnapshot(
        repository=repository,
        branch="main",
        commit_sha="b" * 40,
        status=SnapshotStatus.READY,
    )
    service_content = (
        "def authenticate():\n    return 'signed-in'\n\n"
        "def invoice_total():\n    return 42\n"
    )
    test_content = "def test_authenticate():\n    assert authenticate()\n"
    service = _source(snapshot, "src/service.py", service_content)
    tests = _source(snapshot, "tests/test_service.py", test_content)
    session.add_all([repository, snapshot, service, tests])
    session.flush()
    session.add_all(
        [
            CodeSymbol(
                source_file=service,
                kind=SymbolKind.MODULE,
                name="service",
                qualified_name="src.service",
                start_line=1,
                end_line=5,
            ),
            CodeSymbol(
                source_file=service,
                kind=SymbolKind.FUNCTION,
                name="authenticate",
                qualified_name="src.service.authenticate",
                start_line=1,
                end_line=2,
            ),
            CodeSymbol(
                source_file=service,
                kind=SymbolKind.FUNCTION,
                name="invoice_total",
                qualified_name="src.service.invoice_total",
                start_line=4,
                end_line=5,
            ),
            CodeSymbol(
                source_file=tests,
                kind=SymbolKind.MODULE,
                name="test_service",
                qualified_name="tests.test_service",
                start_line=1,
                end_line=2,
            ),
            CodeSymbol(
                source_file=tests,
                kind=SymbolKind.FUNCTION,
                name="test_authenticate",
                qualified_name="tests.test_service.test_authenticate",
                start_line=1,
                end_line=2,
            ),
        ]
    )
    session.commit()
    return repository, snapshot


def _dataset() -> EvaluationDataset:
    return EvaluationDataset.model_validate(
        {
            "schema_version": 1,
            "dataset_id": "demo.v1",
            "description": "Test benchmark",
            "repositories": [
                {
                    "repository": "https://github.com/acme/demo",
                    "commit": "b" * 40,
                    "cases": [
                        {
                            "id": "auth-implementation",
                            "question": "How is authenticate implemented?",
                            "question_type": "implementation",
                            "expected_files": ["src/service.py"],
                            "expected_symbols": ["src.service.authenticate"],
                            "symbol_query": "authenticate",
                            "expected_routing": {
                                "category": "implementation",
                                "strategy": "hybrid_retrieval",
                            },
                            "expected_tools": ["search_code"],
                        },
                        {
                            "id": "invoice-symbol",
                            "question": "Where is `invoice_total` defined?",
                            "question_type": "symbol_lookup",
                            "expected_files": ["src/service.py"],
                            "expected_symbols": ["src.service.invoice_total"],
                            "symbol_query": "invoice_total",
                            "expected_routing": {
                                "category": "symbol_lookup",
                                "strategy": "direct_symbol_lookup",
                            },
                            "expected_tools": ["lookup_symbol"],
                        },
                        {
                            "id": "commit-metadata",
                            "question": "What commit was indexed?",
                            "question_type": "repository_metadata",
                            "retrieval": False,
                            "expected_routing": {
                                "category": "repository_metadata",
                                "strategy": "repository_metadata",
                            },
                            "expected_tools": ["repository_metadata"],
                        },
                    ],
                }
            ],
        }
    )


def test_versioned_dataset_loads_with_content_hash(tmp_path) -> None:
    path = tmp_path / "dataset.json"
    payload = _dataset().model_dump(mode="json")
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    loaded, digest = load_dataset(path)

    assert loaded.dataset_id == "demo.v1"
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_checked_in_sample_dataset_is_valid_and_commit_pinned() -> None:
    path = Path(__file__).parents[1] / "evaluations/datasets/v1/sampleproject.json"

    dataset, digest = load_dataset(path)

    assert dataset.schema_version == 1
    assert dataset.repositories[0].commit == "621e4974ca25ce531773def586ba3ed8e736b3fc"
    assert len(digest) == 64


def test_dataset_rejects_non_full_commit() -> None:
    payload = _dataset().model_dump(mode="json")
    payload["repositories"][0]["commit"] = "main"

    with pytest.raises(ValidationError, match="full 40-character"):
        EvaluationDataset.model_validate(payload)


def test_evaluation_runs_retrieval_and_routing_comparison_end_to_end(
    session_factory,
) -> None:
    settings = Settings(_env_file=None, embedding_dimensions=16)
    vectors = EvaluationVectors()
    embeddings = EvaluationEmbeddings()
    with session_factory() as session:
        _, snapshot = _seed(session)
        RetrievalIndexer(session, settings, vectors, embeddings).index_snapshot(snapshot)

        report = EvaluationRunner(session, settings, vectors, embeddings).run(
            _dataset(),
            "c" * 64,
            configurations=("semantic", "hybrid"),
            k_values=(1, 3),
        )

    assert [item.configuration for item in report.retrieval_summaries] == [
        "semantic",
        "hybrid",
    ]
    assert report.retrieval_comparisons[0].baseline == "semantic"
    assert report.retrieval_comparisons[0].contender == "hybrid"
    assert report.routing_category.accuracy == 1
    assert report.routing_strategy.accuracy == 1
    assert report.symbol_lookup.accuracy == 1
    assert report.tool_selection.accuracy == 1
    assert report.model_assisted_metrics.enabled is False
    assert all(
        "/blob/" + "b" * 40 in evidence.source_url
        for result in report.retrieval_cases
        for evidence in result.evidence
    )
    assert json.loads(report.model_dump_json())["dataset_sha256"] == "c" * 64


def test_evaluation_requires_the_exact_dataset_snapshot(session_factory) -> None:
    with session_factory() as session:
        runner = EvaluationRunner(
            session,
            Settings(_env_file=None, embedding_dimensions=16),
            EvaluationVectors(),
            EvaluationEmbeddings(),
        )

        with pytest.raises(EvaluationError, match="is not ingested"):
            runner.run(_dataset(), "d" * 64)
