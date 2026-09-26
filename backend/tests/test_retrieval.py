import hashlib
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.code_symbol import CodeSymbol, SymbolKind
from app.models.repository import Repository
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.models.source_file import FileParseStatus, SourceFile
from app.retrieval.embeddings import HashingEmbeddingProvider
from app.retrieval.service import HybridRetriever, RetrievalFilters, RetrievalIndexer
from app.retrieval.vector_store import VectorHit, VectorPoint


class IntentEmbeddings:
    name = "test-intent"
    dimensions = 16

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vectors.append(
                [1.0, 0.0] + [0.0] * 14
                if "auth" in text.lower() or "sign in" in text.lower()
                else [0.0, 1.0] + [0.0] * 14
            )
        return vectors


class MemoryVectors:
    def __init__(self) -> None:
        self.points: dict[uuid.UUID, list[VectorPoint]] = {}

    def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        del collection_name, dimensions

    def replace_snapshot(
        self,
        collection_name: str,
        snapshot_id: uuid.UUID,
        points: list[VectorPoint],
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
        hits = []
        for point in self.points.get(snapshot_id, []):
            payload = point.payload
            matches = (
                (not filepath or payload["filepath"] == filepath)
                and (not symbol_kind or payload["symbol_kind"] == symbol_kind)
                and (not language or payload["language"] == language)
            )
            if matches:
                score = sum(
                    left * right for left, right in zip(vector, point.vector, strict=True)
                )
                hits.append(VectorHit(point.id, score))
        return sorted(hits, key=lambda hit: -hit.score)[:limit]


def _seed(session: Session) -> tuple[Repository, RepositorySnapshot]:
    repository = Repository(
        github_url="https://github.com/acme/demo", owner="acme", name="demo"
    )
    snapshot = RepositorySnapshot(
        repository=repository,
        branch="main",
        commit_sha="a" * 40,
        status=SnapshotStatus.READY,
    )
    content = "def authenticate():\n    return 'auth'\n\ndef invoice_total():\n    return 42\n"
    source = SourceFile(
        snapshot=snapshot,
        path="src/service.py",
        module_name="src.service",
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content),
        line_count=5,
        parse_status=FileParseStatus.PARSED,
        content=content,
    )
    session.add_all([repository, snapshot, source])
    session.flush()
    session.add_all(
        [
            CodeSymbol(
                source_file=source,
                kind=SymbolKind.MODULE,
                name="service",
                qualified_name="src.service",
                start_line=1,
                end_line=5,
            ),
            CodeSymbol(
                source_file=source,
                kind=SymbolKind.FUNCTION,
                name="authenticate",
                qualified_name="src.service.authenticate",
                start_line=1,
                end_line=2,
            ),
            CodeSymbol(
                source_file=source,
                kind=SymbolKind.FUNCTION,
                name="invoice_total",
                qualified_name="src.service.invoice_total",
                start_line=4,
                end_line=5,
            ),
        ]
    )
    session.commit()
    return repository, snapshot


def test_hashing_embeddings_are_deterministic_and_local() -> None:
    provider = HashingEmbeddingProvider(dimensions=64)
    assert provider.embed(["parse Python source"])[0] == provider.embed(["parse Python source"])[0]
    assert len(provider.embed(["parse Python source"])[0]) == 64


def test_semantic_lexical_hybrid_and_filters_are_snapshot_scoped(session_factory) -> None:
    settings = Settings(embedding_dimensions=16, retrieval_lexical_candidate_limit=100)
    vectors = MemoryVectors()
    embeddings = IntentEmbeddings()
    with session_factory() as session:
        repository, snapshot = _seed(session)
        RetrievalIndexer(session, settings, vectors, embeddings).index_snapshot(snapshot)
        retriever = HybridRetriever(session, settings, vectors, embeddings)
        semantic = retriever.search(
            repository, snapshot, "sign in", "semantic", RetrievalFilters(), 5
        )
        lexical = retriever.search(
            repository, snapshot, "invoice_total", "lexical", RetrievalFilters(), 5
        )
        hybrid = retriever.search(
            repository,
            snapshot,
            "auth",
            "hybrid",
            RetrievalFilters(symbol_kind=SymbolKind.FUNCTION),
            5,
        )

        assert semantic[0].unit.symbol_name == "authenticate"
        assert lexical[0].unit.symbol_name == "invoice_total"
        assert hybrid[0].unit.symbol_kind == SymbolKind.FUNCTION
        assert all(item.unit.retrieval_index.snapshot_id == snapshot.id for item in hybrid)
