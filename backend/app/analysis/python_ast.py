import ast
from dataclasses import dataclass

from app.models.code_symbol import SymbolKind


@dataclass(frozen=True)
class ParsedSymbol:
    kind: SymbolKind
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    parent_qualified_name: str | None
    is_async: bool = False


@dataclass(frozen=True)
class ParsedImport:
    module: str
    imported_name: str | None
    alias: str | None
    level: int
    start_line: int
    end_line: int


@dataclass(frozen=True)
class PythonAnalysis:
    symbols: tuple[ParsedSymbol, ...]
    imports: tuple[ParsedImport, ...]
    error: str | None = None


def module_name_from_path(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    if parts[-1] == "__init__" and len(parts) > 1:
        parts.pop()
    return ".".join(parts)


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, module_name: str, line_count: int) -> None:
        self.symbols: list[ParsedSymbol] = [
            ParsedSymbol(
                kind=SymbolKind.MODULE,
                name=module_name.rsplit(".", 1)[-1],
                qualified_name=module_name,
                start_line=1,
                end_line=max(1, line_count),
                parent_qualified_name=None,
            )
        ]
        self.imports: list[ParsedImport] = []
        self._scope: list[ParsedSymbol] = [self.symbols[0]]

    @property
    def _parent(self) -> ParsedSymbol:
        return self._scope[-1]

    @staticmethod
    def _start_line(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        decorator_lines = [decorator.lineno for decorator in node.decorator_list]
        return min([node.lineno, *decorator_lines])

    def _visit_definition(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: SymbolKind,
        *,
        is_async: bool = False,
    ) -> None:
        qualified_name = f"{self._parent.qualified_name}.{node.name}"
        symbol = ParsedSymbol(
            kind=kind,
            name=node.name,
            qualified_name=qualified_name,
            start_line=self._start_line(node),
            end_line=node.end_lineno or node.lineno,
            parent_qualified_name=self._parent.qualified_name,
            is_async=is_async,
        )
        self.symbols.append(symbol)
        self._scope.append(symbol)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._visit_definition(node, SymbolKind.CLASS)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        kind = SymbolKind.METHOD if self._parent.kind == SymbolKind.CLASS else SymbolKind.FUNCTION
        self._visit_definition(node, kind)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        kind = SymbolKind.METHOD if self._parent.kind == SymbolKind.CLASS else SymbolKind.FUNCTION
        self._visit_definition(node, kind, is_async=True)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.imports.append(
                ParsedImport(
                    module=alias.name,
                    imported_name=None,
                    alias=alias.asname,
                    level=0,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for alias in node.names:
            self.imports.append(
                ParsedImport(
                    module=node.module or "",
                    imported_name=alias.name,
                    alias=alias.asname,
                    level=node.level,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                )
            )


def analyze_python(source: str, path: str) -> PythonAnalysis:
    module_name = module_name_from_path(path)
    line_count = len(source.splitlines())
    visitor = _PythonVisitor(module_name, line_count)
    try:
        tree = ast.parse(source, filename=path, type_comments=True)
    except (SyntaxError, ValueError) as exc:
        location = (
            f"line {exc.lineno}" if isinstance(exc, SyntaxError) and exc.lineno else "unknown line"
        )
        detail = exc.msg if isinstance(exc, SyntaxError) else str(exc)
        return PythonAnalysis(
            symbols=tuple(visitor.symbols),
            imports=(),
            error=f"{exc.__class__.__name__} at {location}: {detail}",
        )
    visitor.visit(tree)
    return PythonAnalysis(symbols=tuple(visitor.symbols), imports=tuple(visitor.imports))
