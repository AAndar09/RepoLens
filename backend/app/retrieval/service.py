import itertools
import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.code_symbol import CodeSymbol, SymbolKind
from app.models.repository import Repository
from app.models.retrieval import RetrievalIndexStatus, RetrievalUnit, SnapshotRetrievalIndex
from app.models.snapshot import RepositorySnapshot
from app.models.source_file import SourceFile
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider, lexical_tokens
from app.retrieval.vector_store import VectorPoint, VectorStore


class RetrievalNotReadyError(RuntimeError):
    pass


class RetrievalUnitLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetrievalFilters:
    filepath: str | None = None
    filepath_prefix: str | None = None
    symbol_kind: SymbolKind | None = None
    language: str | None = None


@dataclass(frozen=True)
class UnitDefinition:
    source_file_id: uuid.UUID
    symbol_id: uuid.UUID
    unit_key: str
    language: str
    filepath: str
    symbol_kind: SymbolKind
    symbol_name: str
    qualified_name: str
    start_line: int
    end_line: int
    content: str

    @property
    def search_text(self) -> str:
        return "\n".join(
            (
                self.language,
                self.filepath,
                self.symbol_kind.value,
                self.symbol_name,
                self.qualified_name,
                self.content,
            )
        )


@dataclass(frozen=True)
class RetrievalResult:
    unit: RetrievalUnit
    semantic_score: float | None
    lexical_score: float | None
    hybrid_score: float | None


def _line_chunks(
    source: str, start_line: int, end_line: int, maximum_characters: int
) -> Iterable[tuple[int, int, str]]:
    lines = source.splitlines(keepends=True)[start_line - 1 : end_line]
    if not lines:
        yield start_line, end_line, ""
        return

    current: list[str] = []
    current_start = start_line
    current_length = 0
    line_number = start_line
    for line in lines:
        if current and current_length + len(line) > maximum_characters:
            yield current_start, line_number - 1, "".join(current)
            current = []
            current_start = line_number
            current_length = 0
        if len(line) > maximum_characters:
            if current:
                yield current_start, line_number - 1, "".join(current)
                current = []
                current_length = 0
            for offset in range(0, len(line), maximum_characters):
                yield line_number, line_number, line[offset : offset + maximum_characters]
            current_start = line_number + 1
        else:
            current.append(line)
            current_length += len(line)
        line_number += 1
    if current:
        yield current_start, line_number - 1, "".join(current)


class RetrievalIndexer:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider or create_embedding_provider(settings)

    def _unit_definitions(self, snapshot: RepositorySnapshot) -> list[UnitDefinition]:
        definitions: list[UnitDefinition] = []
        rows = self.session.execute(
            select(CodeSymbol, SourceFile)
            .join(SourceFile, SourceFile.id == CodeSymbol.source_file_id)
            .where(SourceFile.snapshot_id == snapshot.id)
            .order_by(SourceFile.path, CodeSymbol.start_line, CodeSymbol.end_line)
        ).all()
        for symbol, source_file in rows:
            for chunk_index, (start_line, end_line, content) in enumerate(
                _line_chunks(
                    source_file.content,
                    symbol.start_line,
                    symbol.end_line,
                    self.settings.retrieval_max_unit_chars,
                )
            ):
                definitions.append(
                    UnitDefinition(
                        source_file_id=source_file.id,
                        symbol_id=symbol.id,
                        unit_key=f"symbol:{symbol.id}:{chunk_index}",
                        language="python",
                        filepath=source_file.path,
                        symbol_kind=symbol.kind,
                        symbol_name=symbol.name,
                        qualified_name=symbol.qualified_name,
                        start_line=start_line,
                        end_line=end_line,
                        content=content,
                    )
                )
                if len(definitions) > self.settings.retrieval_max_units_per_snapshot:
                    raise RetrievalUnitLimitError(
                        "Snapshot exceeds the configured retrieval-unit limit"
                    )
        return definitions

    def _points(self, units: list[RetrievalUnit]) -> Iterable[VectorPoint]:
        for start in range(0, len(units), self.settings.embedding_batch_size):
            batch = units[start : start + self.settings.embedding_batch_size]
            vectors = self.embedding_provider.embed([unit.search_text for unit in batch])
            if len(vectors) != len(batch) or any(
                len(vector) != self.embedding_provider.dimensions for vector in vectors
            ):
                raise ValueError("Embedding provider returned vectors with an unexpected dimension")
            for unit, vector in zip(batch, vectors, strict=True):
                yield VectorPoint(
                    id=unit.id,
                    vector=vector,
                    payload={
                        "snapshot_id": str(unit.retrieval_index.snapshot_id),
                        "filepath": unit.filepath,
                        "symbol_kind": unit.symbol_kind.value if unit.symbol_kind else None,
                        "language": unit.language,
                    },
                )

    def index_snapshot(
        self, snapshot: RepositorySnapshot, *, refresh: bool = False
    ) -> SnapshotRetrievalIndex:
        retrieval_index = self.session.scalar(
            select(SnapshotRetrievalIndex).where(SnapshotRetrievalIndex.snapshot_id == snapshot.id)
        )
        if (
            retrieval_index is not None
            and retrieval_index.status == RetrievalIndexStatus.READY
            and retrieval_index.embedding_provider == self.embedding_provider.name
            and retrieval_index.embedding_dimensions == self.embedding_provider.dimensions
            and retrieval_index.collection_name == self.settings.qdrant_collection
            and not refresh
        ):
            return retrieval_index

        if retrieval_index is None:
            retrieval_index = SnapshotRetrievalIndex(
                snapshot_id=snapshot.id,
                embedding_provider=self.embedding_provider.name,
                embedding_dimensions=self.embedding_provider.dimensions,
                collection_name=self.settings.qdrant_collection,
            )
            self.session.add(retrieval_index)
        else:
            retrieval_index.units.clear()
            retrieval_index.embedding_provider = self.embedding_provider.name
            retrieval_index.embedding_dimensions = self.embedding_provider.dimensions
            retrieval_index.collection_name = self.settings.qdrant_collection
            retrieval_index.unit_count = 0
            retrieval_index.error_message = None
            retrieval_index.indexed_at = None
        retrieval_index.status = RetrievalIndexStatus.INDEXING
        self.session.commit()
        self.session.refresh(retrieval_index)

        try:
            definitions = self._unit_definitions(snapshot)
            units = [
                RetrievalUnit(
                    retrieval_index=retrieval_index,
                    source_file_id=definition.source_file_id,
                    symbol_id=definition.symbol_id,
                    unit_key=definition.unit_key,
                    language=definition.language,
                    filepath=definition.filepath,
                    symbol_kind=definition.symbol_kind,
                    symbol_name=definition.symbol_name,
                    qualified_name=definition.qualified_name,
                    start_line=definition.start_line,
                    end_line=definition.end_line,
                    content=definition.content,
                    search_text=definition.search_text,
                )
                for definition in definitions
            ]
            self.session.add_all(units)
            self.session.flush()
            self.vector_store.ensure_collection(
                retrieval_index.collection_name,
                self.embedding_provider.dimensions,
            )
            self.vector_store.replace_snapshot(
                retrieval_index.collection_name,
                snapshot.id,
                list(self._points(units)),
            )
            retrieval_index.status = RetrievalIndexStatus.READY
            retrieval_index.unit_count = len(units)
            retrieval_index.error_message = None
            retrieval_index.indexed_at = datetime.now(UTC)
            self.session.commit()
            self.session.refresh(retrieval_index)
            return retrieval_index
        except Exception as exc:
            self.session.rollback()
            failed_index = self.session.get(SnapshotRetrievalIndex, retrieval_index.id)
            if failed_index is not None:
                failed_index.status = RetrievalIndexStatus.FAILED
                failed_index.error_message = str(exc)[:2_000]
                self.session.commit()
            raise


class HybridRetriever:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider or create_embedding_provider(settings)

    @staticmethod
    def _escaped_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _filtered_units_query(
        self, retrieval_index: SnapshotRetrievalIndex, filters: RetrievalFilters
    ):
        query = select(RetrievalUnit).where(RetrievalUnit.retrieval_index_id == retrieval_index.id)
        if filters.filepath:
            query = query.where(RetrievalUnit.filepath == filters.filepath)
        if filters.filepath_prefix:
            path_prefix = f"{self._escaped_like(filters.filepath_prefix)}%"
            query = query.where(RetrievalUnit.filepath.like(path_prefix, escape="\\"))
        if filters.symbol_kind:
            query = query.where(RetrievalUnit.symbol_kind == filters.symbol_kind)
        if filters.language:
            query = query.where(RetrievalUnit.language == filters.language)
        return query

    @staticmethod
    def _lexical_score(unit: RetrievalUnit, query: str) -> float:
        tokens = lexical_tokens(query)
        if not tokens:
            return 0.0
        text = unit.search_text.lower()
        score = 0.0
        for token in tokens:
            occurrences = text.count(token)
            if occurrences:
                score += 1.0 + math.log(occurrences)
            if unit.symbol_name and token == unit.symbol_name.lower():
                score += 3.0
        if query.lower() in text:
            score += 2.0
        return score / len(tokens)

    def lexical_search(
        self,
        retrieval_index: SnapshotRetrievalIndex,
        query: str,
        filters: RetrievalFilters,
        limit: int,
    ) -> list[tuple[RetrievalUnit, float]]:
        candidates = list(
            self.session.scalars(
                self._filtered_units_query(retrieval_index, filters)
                .order_by(RetrievalUnit.filepath, RetrievalUnit.start_line)
                .limit(self.settings.retrieval_lexical_candidate_limit)
            )
        )
        ranked = [(unit, self._lexical_score(unit, query)) for unit in candidates]
        ranked = [item for item in ranked if item[1] > 0]
        return sorted(
            ranked,
            key=lambda item: (-item[1], item[0].filepath, item[0].start_line),
        )[:limit]

    def semantic_search(
        self,
        retrieval_index: SnapshotRetrievalIndex,
        snapshot: RepositorySnapshot,
        query: str,
        filters: RetrievalFilters,
        limit: int,
    ) -> list[tuple[RetrievalUnit, float]]:
        vector = self.embedding_provider.embed([query])[0]
        hits = self.vector_store.search(
            retrieval_index.collection_name,
            vector,
            snapshot.id,
            limit,
            filepath=filters.filepath,
            symbol_kind=filters.symbol_kind.value if filters.symbol_kind else None,
            language=filters.language,
        )
        units_by_id = {
            unit.id: unit
            for unit in self.session.scalars(
                self._filtered_units_query(retrieval_index, filters).where(
                    RetrievalUnit.id.in_([hit.id for hit in hits])
                )
            )
        }
        return [(units_by_id[hit.id], hit.score) for hit in hits if hit.id in units_by_id]

    @staticmethod
    def _ready_index(session: Session, snapshot: RepositorySnapshot) -> SnapshotRetrievalIndex:
        retrieval_index = session.scalar(
            select(SnapshotRetrievalIndex).where(SnapshotRetrievalIndex.snapshot_id == snapshot.id)
        )
        if retrieval_index is None or retrieval_index.status != RetrievalIndexStatus.READY:
            raise RetrievalNotReadyError("Snapshot has not been indexed for retrieval")
        return retrieval_index

    def search(
        self,
        repository: Repository,
        snapshot: RepositorySnapshot,
        query: str,
        mode: str,
        filters: RetrievalFilters,
        limit: int,
    ) -> list[RetrievalResult]:
        del repository  # Retrieval scope is enforced by the snapshot in the route and index query.
        retrieval_index = self._ready_index(self.session, snapshot)
        candidate_limit = max(limit * 5, 50)
        lexical = (
            self.lexical_search(retrieval_index, query, filters, candidate_limit)
            if mode in {"lexical", "hybrid"}
            else []
        )
        semantic = (
            self.semantic_search(retrieval_index, snapshot, query, filters, candidate_limit)
            if mode in {"semantic", "hybrid"}
            else []
        )
        lexical_scores = {unit.id: score for unit, score in lexical}
        semantic_scores = {unit.id: score for unit, score in semantic}
        if mode == "lexical":
            return [RetrievalResult(unit, None, score, None) for unit, score in lexical[:limit]]
        if mode == "semantic":
            return [RetrievalResult(unit, score, None, None) for unit, score in semantic[:limit]]

        lexical_ranks = {unit.id: rank for rank, (unit, _) in enumerate(lexical, start=1)}
        semantic_ranks = {unit.id: rank for rank, (unit, _) in enumerate(semantic, start=1)}
        units = {unit.id: unit for unit, _ in itertools.chain(lexical, semantic)}
        fused = []
        for unit_id, unit in units.items():
            score = sum(
                1 / (self.settings.retrieval_hybrid_rrf_k + rank)
                for rank in (lexical_ranks.get(unit_id), semantic_ranks.get(unit_id))
                if rank is not None
            )
            fused.append(
                RetrievalResult(
                    unit=unit,
                    semantic_score=semantic_scores.get(unit_id),
                    lexical_score=lexical_scores.get(unit_id),
                    hybrid_score=score,
                )
            )
        return sorted(
            fused,
            key=lambda item: (-item.hybrid_score, item.unit.filepath, item.unit.start_line),
        )[:limit]
