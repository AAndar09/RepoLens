import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.code_symbol import CodeSymbol
from app.models.snapshot import RepositorySnapshot
from app.models.source_file import SourceFile
from app.models.source_import import SourceImport
from app.models.structural_graph import ImportResolutionStatus, ModuleImportResolution


class GraphEntityNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class GraphSummary:
    snapshot_id: uuid.UUID
    module_count: int
    symbol_count: int
    import_count: int
    resolved_import_count: int
    unresolved_import_count: int
    ambiguous_import_count: int
    complete: bool


@dataclass(frozen=True)
class SymbolContainment:
    symbol: CodeSymbol
    source_file: SourceFile
    parent: CodeSymbol | None
    children: tuple[CodeSymbol, ...]


class StructuralGraphService:
    def __init__(self, session: Session, source_roots: tuple[str, ...] = ("src",)) -> None:
        self.session = session
        self.source_roots = frozenset(source_roots)

    def _module_aliases(self, source_file: SourceFile) -> set[str]:
        aliases = {source_file.module_name}
        path_parts = source_file.path.split("/")
        if len(path_parts) > 1 and path_parts[0] in self.source_roots:
            prefix = f"{path_parts[0]}."
            if source_file.module_name.startswith(prefix):
                aliases.add(source_file.module_name.removeprefix(prefix))
        return aliases

    @staticmethod
    def _relative_module(source_file: SourceFile, source_import: SourceImport) -> str | None:
        parts = source_file.module_name.split(".")
        is_package = source_file.path.endswith("/__init__.py")
        package = parts if is_package else parts[:-1]
        parent_hops = source_import.level - 1
        if parent_hops > len(package):
            return None
        base = package[: len(package) - parent_hops] if parent_hops else package
        if source_import.module:
            base = [*base, *source_import.module.split(".")]
        return ".".join(base)

    def _requested_module(
        self, source_file: SourceFile, source_import: SourceImport
    ) -> str | None:
        if source_import.level:
            return self._relative_module(source_file, source_import)
        return source_import.module

    def build(
        self, snapshot: RepositorySnapshot, *, commit: bool = True
    ) -> GraphSummary:
        files = list(
            self.session.scalars(
                select(SourceFile)
                .where(SourceFile.snapshot_id == snapshot.id)
                .order_by(SourceFile.path)
            )
        )
        aliases: dict[str, list[SourceFile]] = defaultdict(list)
        for source_file in files:
            for alias in self._module_aliases(source_file):
                aliases[alias].append(source_file)

        self.session.execute(
            delete(ModuleImportResolution).where(
                ModuleImportResolution.snapshot_id == snapshot.id
            )
        )
        for source_file in files:
            for source_import in sorted(
                source_file.imports, key=lambda item: (item.start_line, str(item.id))
            ):
                requested = self._requested_module(source_file, source_import)
                candidates = list(aliases.get(requested or "", []))
                if (
                    not candidates
                    and requested
                    and source_import.imported_name
                    and source_import.imported_name != "*"
                ):
                    candidates = list(
                        aliases.get(f"{requested}.{source_import.imported_name}", [])
                    )
                candidate_paths = sorted(item.path for item in candidates)
                if requested is None:
                    status = ImportResolutionStatus.UNRESOLVED
                    reason = "Relative import escapes the indexed package"
                    target = None
                elif len(candidates) == 1:
                    status = ImportResolutionStatus.RESOLVED
                    reason = "Unique indexed module match"
                    target = candidates[0]
                elif len(candidates) > 1:
                    status = ImportResolutionStatus.AMBIGUOUS
                    reason = "Multiple indexed modules match the import"
                    target = None
                else:
                    status = ImportResolutionStatus.UNRESOLVED
                    reason = "No indexed module matches the import"
                    target = None
                self.session.add(
                    ModuleImportResolution(
                        snapshot_id=snapshot.id,
                        source_import=source_import,
                        target_source_file=target,
                        status=status,
                        requested_module=requested or source_import.module,
                        resolved_module=target.module_name if target else None,
                        candidate_paths=candidate_paths,
                        reason=reason,
                    )
                )
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return self.summary(snapshot)

    def summary(self, snapshot: RepositorySnapshot) -> GraphSummary:
        module_count = self.session.scalar(
            select(func.count())
            .select_from(SourceFile)
            .where(SourceFile.snapshot_id == snapshot.id)
        ) or 0
        symbol_count = self.session.scalar(
            select(func.count())
            .select_from(CodeSymbol)
            .join(SourceFile, SourceFile.id == CodeSymbol.source_file_id)
            .where(SourceFile.snapshot_id == snapshot.id)
        ) or 0
        import_count = self.session.scalar(
            select(func.count())
            .select_from(SourceImport)
            .join(SourceFile, SourceFile.id == SourceImport.source_file_id)
            .where(SourceFile.snapshot_id == snapshot.id)
        ) or 0
        status_counts = dict(
            self.session.execute(
                select(ModuleImportResolution.status, func.count())
                .where(ModuleImportResolution.snapshot_id == snapshot.id)
                .group_by(ModuleImportResolution.status)
            ).all()
        )
        resolved = status_counts.get(ImportResolutionStatus.RESOLVED, 0)
        unresolved = status_counts.get(ImportResolutionStatus.UNRESOLVED, 0)
        ambiguous = status_counts.get(ImportResolutionStatus.AMBIGUOUS, 0)
        return GraphSummary(
            snapshot_id=snapshot.id,
            module_count=module_count,
            symbol_count=symbol_count,
            import_count=import_count,
            resolved_import_count=resolved,
            unresolved_import_count=unresolved,
            ambiguous_import_count=ambiguous,
            complete=import_count == resolved + unresolved + ambiguous,
        )

    def module(self, snapshot_id: uuid.UUID, source_file_id: uuid.UUID) -> SourceFile:
        source_file = self.session.scalar(
            select(SourceFile).where(
                SourceFile.id == source_file_id,
                SourceFile.snapshot_id == snapshot_id,
            )
        )
        if source_file is None:
            raise GraphEntityNotFoundError("Module not found in snapshot")
        return source_file

    def symbols_in_module(
        self, snapshot_id: uuid.UUID, source_file_id: uuid.UUID
    ) -> list[CodeSymbol]:
        self.module(snapshot_id, source_file_id)
        return list(
            self.session.scalars(
                select(CodeSymbol)
                .where(CodeSymbol.source_file_id == source_file_id)
                .order_by(CodeSymbol.start_line, CodeSymbol.end_line, CodeSymbol.qualified_name)
            )
        )

    def module_imports(
        self, snapshot_id: uuid.UUID, source_file_id: uuid.UUID
    ) -> list[ModuleImportResolution]:
        self.module(snapshot_id, source_file_id)
        return list(
            self.session.scalars(
                select(ModuleImportResolution)
                .join(SourceImport)
                .where(
                    ModuleImportResolution.snapshot_id == snapshot_id,
                    SourceImport.source_file_id == source_file_id,
                )
                .order_by(SourceImport.start_line, ModuleImportResolution.requested_module)
            )
        )

    def module_importers(
        self, snapshot_id: uuid.UUID, source_file_id: uuid.UUID
    ) -> list[ModuleImportResolution]:
        self.module(snapshot_id, source_file_id)
        return list(
            self.session.scalars(
                select(ModuleImportResolution)
                .join(SourceImport)
                .join(SourceFile, SourceFile.id == SourceImport.source_file_id)
                .where(
                    ModuleImportResolution.snapshot_id == snapshot_id,
                    ModuleImportResolution.status == ImportResolutionStatus.RESOLVED,
                    ModuleImportResolution.target_source_file_id == source_file_id,
                )
                .order_by(SourceFile.path, SourceImport.start_line)
            )
        )

    def symbol_containment(
        self, snapshot_id: uuid.UUID, symbol_id: uuid.UUID
    ) -> SymbolContainment:
        row = self.session.execute(
            select(CodeSymbol, SourceFile)
            .join(SourceFile, SourceFile.id == CodeSymbol.source_file_id)
            .where(CodeSymbol.id == symbol_id, SourceFile.snapshot_id == snapshot_id)
        ).one_or_none()
        if row is None:
            raise GraphEntityNotFoundError("Symbol not found in snapshot")
        symbol, source_file = row
        children = tuple(
            self.session.scalars(
                select(CodeSymbol)
                .where(CodeSymbol.parent_id == symbol.id)
                .order_by(CodeSymbol.start_line, CodeSymbol.qualified_name)
            )
        )
        return SymbolContainment(
            symbol=symbol,
            source_file=source_file,
            parent=symbol.parent,
            children=children,
        )
