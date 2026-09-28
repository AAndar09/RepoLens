import fnmatch
import hashlib
import io
import os
import tokenize
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.python_ast import analyze_python, module_name_from_path
from app.config import Settings
from app.dependencies.extraction import ExtractedDependency, PythonDependencyExtractor
from app.graph.service import StructuralGraphService
from app.models.code_symbol import CodeSymbol
from app.models.dependency import SnapshotDependency
from app.models.repository import Repository, RepositoryStatus
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.models.source_file import FileParseStatus, SourceFile
from app.models.source_import import SourceImport
from app.services.acquisition import AcquiredRepository, GitRepositoryAcquirer


class IngestionResourceLimitError(RuntimeError):
    pass


class RepositoryAcquirer(Protocol):
    def acquire(self, github_url: str) -> AbstractContextManager[AcquiredRepository]: ...


@dataclass(frozen=True)
class CandidateFile:
    path: str
    content: str
    sha256: str
    size_bytes: int
    line_count: int


@dataclass
class ScanResult:
    files: list[CandidateFile]
    dependencies: list[ExtractedDependency]
    skipped_file_count: int = 0
    total_bytes: int = 0


class RepositoryIngestionService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        acquirer: RepositoryAcquirer | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.acquirer = acquirer or GitRepositoryAcquirer(
            timeout_seconds=settings.ingestion_clone_timeout_seconds,
            max_clone_bytes=settings.ingestion_max_clone_bytes,
        )

    def _matches(self, path: str) -> bool:
        included = any(
            fnmatch.fnmatchcase(path, pattern)
            for pattern in self.settings.ingestion_include_patterns
        )
        excluded = any(
            fnmatch.fnmatchcase(path, pattern)
            for pattern in self.settings.ingestion_exclude_patterns
        )
        return included and not excluded

    def _walk_candidates(self, root: Path) -> Iterator[tuple[str, Path]]:
        for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            directories[:] = sorted(
                item
                for item in directories
                if item not in self.settings.ingestion_excluded_directory_names
                and not Path(directory, item).is_symlink()
            )
            for filename in sorted(filenames):
                source_path = Path(directory, filename)
                relative_path = source_path.relative_to(root).as_posix()
                if source_path.is_symlink() or not self._matches(relative_path):
                    continue
                yield relative_path, source_path

    @staticmethod
    def _decode_python(data: bytes) -> str | None:
        if b"\x00" in data:
            return None
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
            return data.decode(encoding)
        except (LookupError, SyntaxError, UnicodeDecodeError):
            return None

    def _scan(self, root: Path) -> ScanResult:
        result = ScanResult(files=[], dependencies=[])
        for relative_path, source_path in self._walk_candidates(root):
            try:
                size = source_path.stat().st_size
            except OSError:
                result.skipped_file_count += 1
                continue
            if size > self.settings.ingestion_max_file_bytes:
                result.skipped_file_count += 1
                continue
            try:
                data = source_path.read_bytes()
            except OSError:
                result.skipped_file_count += 1
                continue
            if len(data) > self.settings.ingestion_max_file_bytes:
                result.skipped_file_count += 1
                continue
            if result.total_bytes + len(data) > self.settings.ingestion_max_total_bytes:
                raise IngestionResourceLimitError(
                    "Repository exceeds the configured source-byte limit"
                )
            content = self._decode_python(data)
            if content is None:
                result.skipped_file_count += 1
                continue
            if len(result.files) >= self.settings.ingestion_max_files:
                raise IngestionResourceLimitError(
                    "Repository exceeds the configured source-file limit"
                )
            result.files.append(
                CandidateFile(
                    path=relative_path,
                    content=content,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    line_count=len(content.splitlines()),
                )
            )
            result.total_bytes += len(data)
        result.dependencies = PythonDependencyExtractor(
            self.settings.ingestion_max_file_bytes,
            self.settings.dependency_max_manifests,
            self.settings.dependency_max_records,
        ).extract(root)
        return result

    def _mark_repository_failed(self, repository: Repository, message: str) -> None:
        repository.status = RepositoryStatus.FAILED
        repository.ingestion_error = message[:2_000]
        self.session.commit()

    def _get_or_create_snapshot(
        self, repository: Repository, acquired: AcquiredRepository
    ) -> tuple[RepositorySnapshot, bool]:
        snapshot = self.session.scalar(
            select(RepositorySnapshot).where(
                RepositorySnapshot.repository_id == repository.id,
                RepositorySnapshot.commit_sha == acquired.commit_sha,
            )
        )
        if snapshot is not None and snapshot.status == SnapshotStatus.READY:
            repository.status = RepositoryStatus.READY
            repository.ingestion_error = None
            self.session.commit()
            return snapshot, True
        if snapshot is None:
            snapshot = RepositorySnapshot(
                repository_id=repository.id,
                branch=acquired.branch,
                commit_sha=acquired.commit_sha,
            )
            self.session.add(snapshot)
        else:
            snapshot.files.clear()
            snapshot.dependencies.clear()
            snapshot.branch = acquired.branch
            snapshot.status = SnapshotStatus.INGESTING
            snapshot.error_message = None
            snapshot.completed_at = None
        self.session.commit()
        self.session.refresh(snapshot)
        return snapshot, False

    def _previous_snapshot(
        self, repository: Repository, commit_sha: str
    ) -> RepositorySnapshot | None:
        return self.session.scalar(
            select(RepositorySnapshot)
            .where(
                RepositorySnapshot.repository_id == repository.id,
                RepositorySnapshot.commit_sha != commit_sha,
                RepositorySnapshot.status == SnapshotStatus.READY,
            )
            .order_by(RepositorySnapshot.completed_at.desc(), RepositorySnapshot.created_at.desc())
            .limit(1)
        )

    def _copy_source_file(
        self, snapshot: RepositorySnapshot, candidate: CandidateFile, previous: SourceFile
    ) -> tuple[SourceFile, int, int, bool]:
        source_file = SourceFile(
            snapshot=snapshot,
            path=candidate.path,
            module_name=previous.module_name,
            sha256=candidate.sha256,
            size_bytes=candidate.size_bytes,
            line_count=candidate.line_count,
            parse_status=previous.parse_status,
            parse_error=previous.parse_error,
            content=candidate.content,
        )
        symbols_by_id: dict[object, CodeSymbol] = {}
        for previous_symbol in previous.symbols:
            symbol = CodeSymbol(
                source_file=source_file,
                kind=previous_symbol.kind,
                name=previous_symbol.name,
                qualified_name=previous_symbol.qualified_name,
                start_line=previous_symbol.start_line,
                end_line=previous_symbol.end_line,
                is_async=previous_symbol.is_async,
            )
            symbols_by_id[previous_symbol.id] = symbol
        for previous_symbol in previous.symbols:
            if previous_symbol.parent_id is not None:
                symbols_by_id[previous_symbol.id].parent = symbols_by_id[
                    previous_symbol.parent_id
                ]
        for previous_import in previous.imports:
            source_file.imports.append(
                SourceImport(
                    module=previous_import.module,
                    imported_name=previous_import.imported_name,
                    alias=previous_import.alias,
                    level=previous_import.level,
                    start_line=previous_import.start_line,
                    end_line=previous_import.end_line,
                )
            )
        return (
            source_file,
            len(previous.symbols),
            len(previous.imports),
            previous.parse_status == FileParseStatus.MALFORMED,
        )

    @staticmethod
    def _parse_source_file(
        snapshot: RepositorySnapshot, candidate: CandidateFile
    ) -> tuple[SourceFile, int, int, bool]:
        analysis = analyze_python(candidate.content, candidate.path)
        source_file = SourceFile(
            snapshot=snapshot,
            path=candidate.path,
            module_name=module_name_from_path(candidate.path),
            sha256=candidate.sha256,
            size_bytes=candidate.size_bytes,
            line_count=candidate.line_count,
            parse_status=(
                FileParseStatus.MALFORMED if analysis.error else FileParseStatus.PARSED
            ),
            parse_error=analysis.error,
            content=candidate.content,
        )
        symbols_by_name: dict[str, CodeSymbol] = {}
        for parsed_symbol in analysis.symbols:
            symbol = CodeSymbol(
                source_file=source_file,
                parent=symbols_by_name.get(parsed_symbol.parent_qualified_name or ""),
                kind=parsed_symbol.kind,
                name=parsed_symbol.name,
                qualified_name=parsed_symbol.qualified_name,
                start_line=parsed_symbol.start_line,
                end_line=parsed_symbol.end_line,
                is_async=parsed_symbol.is_async,
            )
            symbols_by_name[parsed_symbol.qualified_name] = symbol
        for parsed_import in analysis.imports:
            source_file.imports.append(
                SourceImport(
                    module=parsed_import.module,
                    imported_name=parsed_import.imported_name,
                    alias=parsed_import.alias,
                    level=parsed_import.level,
                    start_line=parsed_import.start_line,
                    end_line=parsed_import.end_line,
                )
            )
        return source_file, len(analysis.symbols), len(analysis.imports), analysis.error is not None

    def _persist_scan(
        self,
        snapshot: RepositorySnapshot,
        result: ScanResult,
        previous_snapshot: RepositorySnapshot | None,
    ) -> None:
        symbol_count = 0
        import_count = 0
        malformed_count = 0
        reused_count = 0
        processed_count = 0
        previous_files = (
            {source_file.path: source_file for source_file in previous_snapshot.files}
            if previous_snapshot is not None
            else {}
        )
        for candidate in result.files:
            previous = previous_files.get(candidate.path)
            if previous is not None and previous.sha256 == candidate.sha256:
                source_file, symbols, imports, malformed = self._copy_source_file(
                    snapshot, candidate, previous
                )
                reused_count += 1
            else:
                source_file, symbols, imports, malformed = self._parse_source_file(
                    snapshot, candidate
                )
                processed_count += 1
            symbol_count += symbols
            import_count += imports
            malformed_count += int(malformed)
            self.session.add(source_file)

        for item in result.dependencies:
            self.session.add(
                SnapshotDependency(
                    snapshot=snapshot,
                    ecosystem=item.ecosystem,
                    name=item.name,
                    normalized_name=item.normalized_name,
                    specifier=item.specifier,
                    resolved_version=item.resolved_version,
                    version_resolved=item.resolved_version is not None,
                    source_type=item.source_type,
                    source_path=item.source_path,
                    source_line=item.source_line,
                    declaration=item.declaration,
                    scope=item.scope,
                    marker=item.marker,
                )
            )

        self.session.flush()
        StructuralGraphService(self.session, self.settings.graph_source_root_names).build(
            snapshot, commit=False
        )

        snapshot.status = SnapshotStatus.READY
        snapshot.error_message = None
        snapshot.file_count = len(result.files)
        snapshot.parsed_file_count = len(result.files) - malformed_count
        snapshot.malformed_file_count = malformed_count
        snapshot.skipped_file_count = result.skipped_file_count
        snapshot.reused_file_count = reused_count
        snapshot.processed_file_count = processed_count
        snapshot.removed_file_count = len(
            set(previous_files) - {candidate.path for candidate in result.files}
        )
        snapshot.symbol_count = symbol_count
        snapshot.import_count = import_count
        snapshot.total_bytes = result.total_bytes
        snapshot.completed_at = datetime.now(UTC)
        snapshot.repository.status = RepositoryStatus.READY
        snapshot.repository.ingestion_error = None
        self.session.commit()
        self.session.refresh(snapshot)

    def ingest(self, repository: Repository) -> RepositorySnapshot:
        repository.status = RepositoryStatus.INGESTING
        repository.ingestion_error = None
        self.session.commit()
        try:
            with self.acquirer.acquire(repository.github_url) as acquired:
                previous_snapshot = self._previous_snapshot(repository, acquired.commit_sha)
                snapshot, complete = self._get_or_create_snapshot(repository, acquired)
                if complete:
                    return snapshot
                try:
                    result = self._scan(acquired.path)
                    self._persist_scan(snapshot, result, previous_snapshot)
                except Exception as exc:
                    self.session.rollback()
                    snapshot = self.session.get(RepositorySnapshot, snapshot.id)
                    if snapshot is not None:
                        snapshot.status = SnapshotStatus.FAILED
                        snapshot.error_message = str(exc)[:2_000]
                        snapshot.completed_at = datetime.now(UTC)
                    repository = self.session.get(Repository, repository.id)
                    if repository is not None:
                        repository.status = RepositoryStatus.FAILED
                        repository.ingestion_error = str(exc)[:2_000]
                    self.session.commit()
                    raise
                return snapshot
        except Exception as exc:
            if repository.status != RepositoryStatus.FAILED:
                self._mark_repository_failed(repository, str(exc))
            raise
