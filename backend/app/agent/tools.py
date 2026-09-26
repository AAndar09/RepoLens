from dataclasses import dataclass
from urllib.parse import quote

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.graph.service import StructuralGraphService
from app.models.code_symbol import CodeSymbol
from app.models.repository import Repository
from app.models.snapshot import RepositorySnapshot
from app.models.source_file import SourceFile
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.service import HybridRetriever, RetrievalFilters
from app.retrieval.vector_store import VectorStore
from app.schemas.investigation import (
    CitationResponse,
    LookupSymbolArguments,
    ReadSourceArguments,
    RepositoryMetadataArguments,
    SearchCodeArguments,
    StructuralLookupArguments,
    ToolName,
    ToolRequest,
)


class ToolInputError(ValueError):
    pass


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceCandidate:
    title: str
    data: dict[str, object]
    filepath: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    excerpt: str = ""


@dataclass(frozen=True)
class ToolExecution:
    summary: str
    evidence: tuple[EvidenceCandidate, ...]


ARGUMENT_TYPES: dict[ToolName, type[BaseModel]] = {
    "search_code": SearchCodeArguments,
    "lookup_symbol": LookupSymbolArguments,
    "read_source": ReadSourceArguments,
    "structural_lookup": StructuralLookupArguments,
    "repository_metadata": RepositoryMetadataArguments,
}


def tool_catalog() -> dict[str, object]:
    descriptions = {
        "search_code": "Semantic or hybrid search over the ready snapshot retrieval index.",
        "lookup_symbol": "Exact lookup by symbol name or qualified name.",
        "read_source": "Read a bounded line range from one indexed source file.",
        "structural_lookup": "Inspect module imports/importers/symbols or symbol containment.",
        "repository_metadata": "Read repository, snapshot, ingestion, and graph counts.",
    }
    return {
        name: {
            "description": descriptions[name],
            "arguments_schema": argument_type.model_json_schema(),
        }
        for name, argument_type in ARGUMENT_TYPES.items()
    }


class ControlledToolset:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        repository: Repository,
        snapshot: RepositorySnapshot,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repository = repository
        self.snapshot = snapshot
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.graph = StructuralGraphService(session, settings.graph_source_root_names)

    def repository_context(self) -> dict[str, object]:
        return {
            "repository_id": str(self.repository.id),
            "owner": self.repository.owner,
            "name": self.repository.name,
            "snapshot_id": str(self.snapshot.id),
            "branch": self.snapshot.branch,
            "commit_sha": self.snapshot.commit_sha,
            "tools": tool_catalog(),
        }

    def _source_url(self, filepath: str, start_line: int, end_line: int) -> str:
        fragment = f"#L{start_line}"
        if end_line != start_line:
            fragment += f"-L{end_line}"
        return (
            f"https://github.com/{self.repository.owner}/{self.repository.name}/blob/"
            f"{self.snapshot.commit_sha}/{quote(filepath, safe='/')}{fragment}"
        )

    def citation(
        self, candidate: EvidenceCandidate, citation_id: str
    ) -> CitationResponse | None:
        if (
            candidate.filepath is None
            or candidate.start_line is None
            or candidate.end_line is None
        ):
            return None
        return CitationResponse(
            id=citation_id,
            snapshot_id=self.snapshot.id,
            commit_sha=self.snapshot.commit_sha,
            filepath=candidate.filepath,
            start_line=candidate.start_line,
            end_line=candidate.end_line,
            source_url=self._source_url(
                candidate.filepath, candidate.start_line, candidate.end_line
            ),
            title=candidate.title,
            excerpt=candidate.excerpt[:4_000],
        )

    def execute(self, request: ToolRequest) -> ToolExecution:
        argument_type = ARGUMENT_TYPES[request.tool]
        try:
            arguments = argument_type.model_validate(request.arguments)
        except ValidationError as exc:
            raise ToolInputError(f"Invalid {request.tool} arguments: {exc}") from exc
        handlers = {
            "search_code": self._search_code,
            "lookup_symbol": self._lookup_symbol,
            "read_source": self._read_source,
            "structural_lookup": self._structural_lookup,
            "repository_metadata": self._repository_metadata,
        }
        return handlers[request.tool](arguments)

    def _search_code(self, raw_arguments: BaseModel) -> ToolExecution:
        arguments = SearchCodeArguments.model_validate(raw_arguments)
        results = HybridRetriever(
            self.session,
            self.settings,
            self.vector_store,
            self.embedding_provider,
        ).search(
            self.repository,
            self.snapshot,
            arguments.query,
            arguments.mode,
            RetrievalFilters(
                filepath=arguments.filepath,
                filepath_prefix=arguments.filepath_prefix,
                symbol_kind=arguments.symbol_kind,
                language="python",
            ),
            arguments.limit,
        )
        evidence = tuple(
            EvidenceCandidate(
                title=result.unit.qualified_name or result.unit.filepath,
                filepath=result.unit.filepath,
                start_line=result.unit.start_line,
                end_line=result.unit.end_line,
                excerpt=result.unit.content,
                data={
                    "qualified_name": result.unit.qualified_name,
                    "symbol_kind": (
                        result.unit.symbol_kind.value if result.unit.symbol_kind else None
                    ),
                    "semantic_score": result.semantic_score,
                    "lexical_score": result.lexical_score,
                    "hybrid_score": result.hybrid_score,
                    "content": result.unit.content,
                },
            )
            for result in results
        )
        return ToolExecution(
            summary=f"Found {len(evidence)} code search results",
            evidence=evidence,
        )

    def _lookup_symbol(self, raw_arguments: BaseModel) -> ToolExecution:
        arguments = LookupSymbolArguments.model_validate(raw_arguments)
        query = (
            select(CodeSymbol, SourceFile)
            .join(SourceFile, SourceFile.id == CodeSymbol.source_file_id)
            .where(
                SourceFile.snapshot_id == self.snapshot.id,
                or_(
                    CodeSymbol.name == arguments.name,
                    CodeSymbol.qualified_name == arguments.name,
                ),
            )
            .order_by(SourceFile.path, CodeSymbol.start_line)
            .limit(arguments.limit)
        )
        if arguments.kind is not None:
            query = query.where(CodeSymbol.kind == arguments.kind)
        rows = self.session.execute(query).all()
        evidence = tuple(
            EvidenceCandidate(
                title=symbol.qualified_name,
                filepath=source_file.path,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                excerpt="\n".join(
                    source_file.content.splitlines()[symbol.start_line - 1 : symbol.end_line]
                ),
                data={
                    "symbol_id": str(symbol.id),
                    "kind": symbol.kind.value,
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "parent_id": str(symbol.parent_id) if symbol.parent_id else None,
                },
            )
            for symbol, source_file in rows
        )
        return ToolExecution(summary=f"Found {len(evidence)} matching symbols", evidence=evidence)

    def _read_source(self, raw_arguments: BaseModel) -> ToolExecution:
        arguments = ReadSourceArguments.model_validate(raw_arguments)
        source_file = self.session.scalar(
            select(SourceFile).where(
                SourceFile.snapshot_id == self.snapshot.id,
                SourceFile.path == arguments.filepath,
            )
        )
        if source_file is None:
            raise ToolExecutionError("Source file was not found in the selected snapshot")
        line_count = max(1, source_file.line_count)
        start_line = min(arguments.start_line, line_count)
        end_line = arguments.end_line or min(
            line_count, start_line + self.settings.agent_max_source_lines - 1
        )
        end_line = min(end_line, line_count)
        if end_line < start_line:
            raise ToolInputError("end_line must be greater than or equal to start_line")
        if end_line - start_line + 1 > self.settings.agent_max_source_lines:
            raise ToolInputError("Requested source range exceeds the configured line limit")
        excerpt = "\n".join(source_file.content.splitlines()[start_line - 1 : end_line])
        evidence = EvidenceCandidate(
            title=source_file.path,
            filepath=source_file.path,
            start_line=start_line,
            end_line=end_line,
            excerpt=excerpt,
            data={
                "module_name": source_file.module_name,
                "parse_status": source_file.parse_status.value,
                "content": excerpt,
            },
        )
        return ToolExecution(
            summary=f"Read {source_file.path} lines {start_line}-{end_line}",
            evidence=(evidence,),
        )

    def _structural_lookup(self, raw_arguments: BaseModel) -> ToolExecution:
        arguments = StructuralLookupArguments.model_validate(raw_arguments)
        if arguments.operation == "module_symbols":
            source_file = self.graph.module(self.snapshot.id, arguments.entity_id)
            symbols = self.graph.symbols_in_module(
                self.snapshot.id, arguments.entity_id
            )[: arguments.limit]
            evidence = tuple(
                EvidenceCandidate(
                    title=symbol.qualified_name,
                    filepath=source_file.path,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    excerpt="\n".join(
                        source_file.content.splitlines()[symbol.start_line - 1 : symbol.end_line]
                    ),
                    data={
                        "relationship": "module_contains_symbol",
                        "module_id": str(source_file.id),
                        "symbol_id": str(symbol.id),
                        "qualified_name": symbol.qualified_name,
                        "kind": symbol.kind.value,
                    },
                )
                for symbol in symbols
            )
        elif arguments.operation in {"module_imports", "module_importers"}:
            summary = self.graph.summary(self.snapshot)
            if not summary.complete:
                raise ToolExecutionError("Structural import graph has not been built")
            relationships = (
                self.graph.module_imports(self.snapshot.id, arguments.entity_id)
                if arguments.operation == "module_imports"
                else self.graph.module_importers(self.snapshot.id, arguments.entity_id)
            )[: arguments.limit]
            evidence = tuple(self._import_evidence(item) for item in relationships)
        else:
            containment = self.graph.symbol_containment(
                self.snapshot.id, arguments.entity_id
            )
            symbol = containment.symbol
            evidence = (
                EvidenceCandidate(
                    title=f"Containment for {symbol.qualified_name}",
                    filepath=containment.source_file.path,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    excerpt="\n".join(
                        containment.source_file.content.splitlines()[
                            symbol.start_line - 1 : symbol.end_line
                        ]
                    ),
                    data={
                        "relationship": "symbol_containment",
                        "symbol_id": str(symbol.id),
                        "parent": (
                            containment.parent.qualified_name if containment.parent else None
                        ),
                        "children": [child.qualified_name for child in containment.children],
                    },
                ),
            )
        return ToolExecution(
            summary=f"Found {len(evidence)} structural results for {arguments.operation}",
            evidence=evidence,
        )

    def _import_evidence(self, resolution) -> EvidenceCandidate:
        source_import = resolution.source_import
        source_file = source_import.source_file
        return EvidenceCandidate(
            title=f"Import {resolution.requested_module}",
            filepath=source_file.path,
            start_line=source_import.start_line,
            end_line=source_import.end_line,
            excerpt="\n".join(
                source_file.content.splitlines()[
                    source_import.start_line - 1 : source_import.end_line
                ]
            ),
            data={
                "relationship": "module_import",
                "status": resolution.status.value,
                "source_module": source_file.module_name,
                "requested_module": resolution.requested_module,
                "resolved_module": resolution.resolved_module,
                "target_module_id": (
                    str(resolution.target_source_file_id)
                    if resolution.target_source_file_id
                    else None
                ),
                "candidate_paths": resolution.candidate_paths,
                "reason": resolution.reason,
            },
        )

    def _repository_metadata(self, raw_arguments: BaseModel) -> ToolExecution:
        RepositoryMetadataArguments.model_validate(raw_arguments)
        graph = self.graph.summary(self.snapshot)
        evidence = EvidenceCandidate(
            title="Repository snapshot metadata",
            data={
                "owner": self.repository.owner,
                "name": self.repository.name,
                "branch": self.snapshot.branch,
                "commit_sha": self.snapshot.commit_sha,
                "file_count": self.snapshot.file_count,
                "symbol_count": self.snapshot.symbol_count,
                "import_count": self.snapshot.import_count,
                "parsed_file_count": self.snapshot.parsed_file_count,
                "malformed_file_count": self.snapshot.malformed_file_count,
                "resolved_import_count": graph.resolved_import_count,
                "unresolved_import_count": graph.unresolved_import_count,
            },
        )
        return ToolExecution(summary="Loaded repository snapshot metadata", evidence=(evidence,))
