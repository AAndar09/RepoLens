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

from app.analysis.python_ast import PythonAnalysis, analyze_python, module_name_from_path
from app.config import Settings
from app.graph.service import StructuralGraphService
from app.models.code_symbol import CodeSymbol
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
    analysis: PythonAnalysis


@dataclass
class ScanResult:
    files: list[CandidateFile]
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
        result = ScanResult(files=[])
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
                    analysis=analyze_python(content, relative_path),
                )
            )
            result.total_bytes += len(data)
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
            snapshot.branch = acquired.branch
            snapshot.status = SnapshotStatus.INGESTING
            snapshot.error_message = None
            snapshot.completed_at = None
        self.session.commit()
        self.session.refresh(snapshot)
        return snapshot, False

    def _persist_scan(self, snapshot: RepositorySnapshot, result: ScanResult) -> None:
        symbol_count = 0
        import_count = 0
        malformed_count = 0
        for candidate in result.files:
            if candidate.analysis.error:
                malformed_count += 1
            source_file = SourceFile(
                snapshot=snapshot,
                path=candidate.path,
                module_name=module_name_from_path(candidate.path),
                sha256=candidate.sha256,
                size_bytes=candidate.size_bytes,
                line_count=candidate.line_count,
                parse_status=(
                    FileParseStatus.MALFORMED
                    if candidate.analysis.error
                    else FileParseStatus.PARSED
                ),
                parse_error=candidate.analysis.error,
                content=candidate.content,
            )
            symbols_by_name: dict[str, CodeSymbol] = {}
            for parsed_symbol in candidate.analysis.symbols:
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
                symbol_count += 1
            for parsed_import in candidate.analysis.imports:
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
                import_count += 1
            self.session.add(source_file)

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
                snapshot, complete = self._get_or_create_snapshot(repository, acquired)
                if complete:
                    return snapshot
                try:
                    result = self._scan(acquired.path)
                    self._persist_scan(snapshot, result)
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
