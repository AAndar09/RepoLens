import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models.code_symbol import CodeSymbol, SymbolKind
from app.models.repository import Repository, RepositoryStatus
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.models.source_file import FileParseStatus, SourceFile
from app.models.source_import import SourceImport
from app.services.acquisition import AcquiredRepository
from app.services.ingestion import IngestionResourceLimitError, RepositoryIngestionService


class FakeAcquirer:
    def __init__(
        self,
        path: Path,
        *,
        branch: str = "main",
        commit_sha: str = "a" * 40,
    ) -> None:
        self.acquired = AcquiredRepository(path=path, branch=branch, commit_sha=commit_sha)
        self.calls = 0

    @contextmanager
    def acquire(self, github_url: str) -> Iterator[AcquiredRepository]:
        assert github_url.startswith("https://github.com/")
        self.calls += 1
        yield self.acquired


def create_repository(session: Session) -> Repository:
    repository = Repository(
        github_url="https://github.com/example/project",
        owner="example",
        name="project",
    )
    session.add(repository)
    session.commit()
    session.refresh(repository)
    return repository


def create_checkout(root: Path) -> None:
    package = root / "package"
    package.mkdir()
    (package / "__init__.py").write_text("from .service import Greeter\n", encoding="utf-8")
    (package / "service.py").write_text(
        "import os\n\nclass Greeter:\n    def greet(self):\n        return os.name\n",
        encoding="utf-8",
    )
    (root / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (root / "binary.py").write_bytes(b"\x00not-python")
    (root / "README.md").write_text("not source", encoding="utf-8")
    excluded = root / ".venv"
    excluded.mkdir()
    (excluded / "ignored.py").write_text("ignored = True\n", encoding="utf-8")


def test_ingestion_persists_snapshot_files_symbols_and_imports(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    create_checkout(tmp_path)
    acquirer = FakeAcquirer(tmp_path)
    settings = Settings(_env_file=None)

    with session_factory() as session:
        repository = create_repository(session)
        service = RepositoryIngestionService(session, settings, acquirer)

        snapshot = service.ingest(repository)

        assert snapshot.status == SnapshotStatus.READY
        assert snapshot.branch == "main"
        assert snapshot.commit_sha == "a" * 40
        assert snapshot.file_count == 3
        assert snapshot.parsed_file_count == 2
        assert snapshot.malformed_file_count == 1
        assert snapshot.skipped_file_count == 1
        assert snapshot.symbol_count == 5
        assert snapshot.import_count == 2
        assert repository.status == RepositoryStatus.READY

        files = list(session.scalars(select(SourceFile).order_by(SourceFile.path)))
        assert [source_file.path for source_file in files] == [
            "broken.py",
            "package/__init__.py",
            "package/service.py",
        ]
        assert files[0].parse_status == FileParseStatus.MALFORMED
        assert files[0].parse_error and "SyntaxError" in files[0].parse_error
        assert len(files[1].sha256) == 64

        symbols = list(session.scalars(select(CodeSymbol)))
        assert {symbol.kind for symbol in symbols} >= {
            SymbolKind.MODULE,
            SymbolKind.CLASS,
            SymbolKind.METHOD,
        }
        method = next(symbol for symbol in symbols if symbol.kind == SymbolKind.METHOD)
        assert method.qualified_name == "package.service.Greeter.greet"
        assert method.parent is not None
        assert method.parent.qualified_name == "package.service.Greeter"
        assert session.scalar(select(func.count()).select_from(SourceImport)) == 2

        repeated = service.ingest(repository)
        assert repeated.id == snapshot.id
        assert acquirer.calls == 2
        assert session.scalar(select(func.count()).select_from(RepositorySnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(SourceFile)) == 3


def test_source_file_limit_fails_the_snapshot_without_partial_files(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    (tmp_path / "one.py").write_text("one = 1\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("two = 2\n", encoding="utf-8")
    settings = Settings(_env_file=None, ingestion_max_files=1)

    with session_factory() as session:
        repository = create_repository(session)
        service = RepositoryIngestionService(session, settings, FakeAcquirer(tmp_path))

        with pytest.raises(IngestionResourceLimitError, match="source-file limit"):
            service.ingest(repository)

        session.refresh(repository)
        snapshot = session.scalar(select(RepositorySnapshot))
        assert repository.status == RepositoryStatus.FAILED
        assert snapshot is not None
        assert snapshot.status == SnapshotStatus.FAILED
        assert session.scalar(select(func.count()).select_from(SourceFile)) == 0


def test_oversized_file_is_skipped(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    (tmp_path / "small.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "large.py").write_text("x = '" + "a" * 200 + "'\n", encoding="utf-8")
    settings = Settings(_env_file=None, ingestion_max_file_bytes=100)

    with session_factory() as session:
        repository = create_repository(session)
        snapshot = RepositoryIngestionService(
            session, settings, FakeAcquirer(tmp_path)
        ).ingest(repository)

        assert snapshot.status == SnapshotStatus.READY
        assert snapshot.file_count == 1
        assert snapshot.skipped_file_count == 1
        assert session.scalar(select(SourceFile.path)) == "small.py"


def test_total_source_byte_limit_fails_ingestion(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    (tmp_path / "one.py").write_text("one = 1\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("two = 2\n", encoding="utf-8")
    settings = Settings(_env_file=None, ingestion_max_total_bytes=10)

    with session_factory() as session:
        repository = create_repository(session)
        service = RepositoryIngestionService(session, settings, FakeAcquirer(tmp_path))

        with pytest.raises(IngestionResourceLimitError, match="source-byte limit"):
            service.ingest(repository)

        assert repository.status == RepositoryStatus.FAILED
        assert session.scalar(select(func.count()).select_from(SourceFile)) == 0


def test_snapshots_are_scoped_to_repository(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = create_repository(session)
        snapshot = RepositorySnapshot(
            repository_id=repository.id,
            branch="main",
            commit_sha=uuid.uuid4().hex + "12345678",
        )
        session.add(snapshot)
        session.commit()
        assert snapshot.repository_id == repository.id
