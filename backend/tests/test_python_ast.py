from app.analysis.python_ast import analyze_python, module_name_from_path
from app.models.code_symbol import SymbolKind


def test_extracts_symbols_imports_and_line_ranges() -> None:
    source = """import os as operating_system
from .helpers import value as helper_value

@decorator
class Greeter:
    async def greet(self, name: str) -> str:
        def format_name() -> str:
            return name.title()
        return format_name()

def build() -> Greeter:
    return Greeter()
"""

    analysis = analyze_python(source, "package/service.py")

    assert analysis.error is None
    assert [symbol.kind for symbol in analysis.symbols] == [
        SymbolKind.MODULE,
        SymbolKind.CLASS,
        SymbolKind.METHOD,
        SymbolKind.FUNCTION,
        SymbolKind.FUNCTION,
    ]
    symbols = {symbol.qualified_name: symbol for symbol in analysis.symbols}
    assert symbols["package.service.Greeter"].start_line == 4
    assert symbols["package.service.Greeter"].end_line == 9
    assert symbols["package.service.Greeter.greet"].is_async is True
    assert symbols["package.service.Greeter.greet.format_name"].kind == SymbolKind.FUNCTION
    assert symbols["package.service.build"].start_line == 11
    imports = [
        (item.module, item.imported_name, item.alias, item.level) for item in analysis.imports
    ]
    assert imports == [
        ("os", None, "operating_system", 0),
        ("helpers", "value", "helper_value", 1),
    ]


def test_malformed_python_returns_a_file_level_error() -> None:
    analysis = analyze_python("def broken(:\n    pass\n", "broken.py")

    assert analysis.error is not None
    assert "SyntaxError at line 1" in analysis.error
    assert len(analysis.symbols) == 1
    assert analysis.symbols[0].kind == SymbolKind.MODULE


def test_package_init_maps_to_package_module() -> None:
    assert module_name_from_path("repolens/domain/__init__.py") == "repolens.domain"
    assert module_name_from_path("standalone.py") == "standalone"
