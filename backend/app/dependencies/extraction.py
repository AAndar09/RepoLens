import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from app.models.dependency import DependencySourceType

_REQUIREMENTS_PATTERN = re.compile(r"^(?:requirements(?:[-_.].*)?\.txt|.*[-_.]requirements\.txt)$")


@dataclass(frozen=True)
class ExtractedDependency:
    ecosystem: str
    name: str
    normalized_name: str
    specifier: str | None
    resolved_version: str | None
    source_type: DependencySourceType
    source_path: str
    source_line: int | None
    declaration: str
    scope: str
    marker: str | None


class DependencyManifestError(ValueError):
    pass


class PythonDependencyExtractor:
    def __init__(
        self,
        max_manifest_bytes: int,
        max_manifests: int = 100,
        max_dependencies: int = 5_000,
    ) -> None:
        self.max_manifest_bytes = max_manifest_bytes
        self.max_manifests = max_manifests
        self.max_dependencies = max_dependencies

    def extract(self, root: Path) -> list[ExtractedDependency]:
        extracted: list[ExtractedDependency] = []
        manifest_count = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if any(part in {".git", ".venv", "venv", "node_modules"} for part in path.parts):
                continue
            if path.name == "pyproject.toml":
                items = self._pyproject(path, relative)
            elif _REQUIREMENTS_PATTERN.match(path.name.lower()):
                items = self._requirements(path, relative)
            else:
                continue
            manifest_count += 1
            if manifest_count > self.max_manifests:
                raise DependencyManifestError("Repository exceeds the dependency-manifest limit")
            if len(extracted) + len(items) > self.max_dependencies:
                raise DependencyManifestError("Repository exceeds the dependency-record limit")
            extracted.extend(items)
        return extracted

    def _read(self, path: Path) -> str:
        if path.stat().st_size > self.max_manifest_bytes:
            raise DependencyManifestError(f"Dependency manifest exceeds size limit: {path.name}")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise DependencyManifestError(
                f"Could not read dependency manifest: {path.name}"
            ) from exc

    def _requirements(self, path: Path, relative: str) -> list[ExtractedDependency]:
        results: list[ExtractedDependency] = []
        for line_number, raw in enumerate(self._read(path).splitlines(), start=1):
            declaration = raw.strip()
            if not declaration or declaration.startswith(("#", "-")):
                continue
            requirement_text = declaration.split(" #", 1)[0].strip()
            parsed = self._parse_requirement(
                requirement_text,
                DependencySourceType.REQUIREMENTS,
                relative,
                line_number,
                "runtime",
            )
            if parsed is not None:
                results.append(parsed)
        return results

    def _pyproject(self, path: Path, relative: str) -> list[ExtractedDependency]:
        content = self._read(path)
        try:
            document = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            raise DependencyManifestError(f"Malformed dependency manifest: {relative}") from exc
        declarations: list[tuple[str, str]] = []
        project = document.get("project", {})
        declarations.extend((item, "runtime") for item in project.get("dependencies", []))
        for group, values in project.get("optional-dependencies", {}).items():
            declarations.extend((item, f"optional:{group}") for item in values)
        declarations.extend(
            (item, "build") for item in document.get("build-system", {}).get("requires", [])
        )

        results: list[ExtractedDependency] = []
        search_from = 0
        for declaration, scope in declarations:
            offset = content.find(declaration, search_from)
            if offset < 0:
                offset = content.find(declaration)
            line = content.count("\n", 0, offset) + 1 if offset >= 0 else None
            if offset >= 0:
                search_from = offset + len(declaration)
            parsed = self._parse_requirement(
                declaration,
                DependencySourceType.PYPROJECT,
                relative,
                line,
                scope,
            )
            if parsed is not None:
                results.append(parsed)
        return results

    @staticmethod
    def _parse_requirement(
        declaration: str,
        source_type: DependencySourceType,
        source_path: str,
        source_line: int | None,
        scope: str,
    ) -> ExtractedDependency | None:
        try:
            requirement = Requirement(declaration)
        except InvalidRequirement:
            return None
        specifier = str(requirement.specifier) or None
        exact = [
            item.version
            for item in requirement.specifier
            if item.operator in {"==", "==="} and "*" not in item.version
        ]
        resolved_version = exact[0] if len(exact) == 1 and len(requirement.specifier) == 1 else None
        return ExtractedDependency(
            ecosystem="PyPI",
            name=requirement.name,
            normalized_name=canonicalize_name(requirement.name),
            specifier=specifier,
            resolved_version=resolved_version,
            source_type=source_type,
            source_path=source_path,
            source_line=source_line,
            declaration=declaration,
            scope=scope,
            marker=str(requirement.marker) if requirement.marker else None,
        )
