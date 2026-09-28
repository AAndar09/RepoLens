import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class RepositoryAcquisitionError(RuntimeError):
    pass


class RepositoryCloneLimitError(RepositoryAcquisitionError):
    pass


@dataclass(frozen=True)
class AcquiredRepository:
    path: Path
    branch: str
    commit_sha: str


class GitRepositoryAcquirer:
    def __init__(self, timeout_seconds: int, max_clone_bytes: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_clone_bytes = max_clone_bytes

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
                "GIT_LFS_SKIP_SMUDGE": "1",
                "GIT_OPTIONAL_LOCKS": "0",
            }
        )
        return environment

    def _run(self, arguments: list[str], cwd: Path | None = None) -> str:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    f"core.hooksPath={os.devnull}",
                    "-c",
                    "protocol.file.allow=never",
                    "-c",
                    "protocol.ext.allow=never",
                    "-c",
                    "submodule.recurse=false",
                    *arguments,
                ],
                cwd=cwd,
                env=self._environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RepositoryAcquisitionError(
                "Git is not installed in the backend environment"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RepositoryAcquisitionError("Repository acquisition timed out") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            message = detail[-1][:500] if detail else "Git command failed"
            raise RepositoryAcquisitionError(message)
        return result.stdout.strip()

    def _checkout_size(self, root: Path) -> int:
        total = 0
        for directory, _, filenames in os.walk(root, followlinks=False):
            for filename in filenames:
                path = Path(directory, filename)
                if path.is_symlink():
                    continue
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
                if total > self.max_clone_bytes:
                    raise RepositoryCloneLimitError(
                        "Cloned repository exceeds the configured size limit"
                    )
        return total

    @contextmanager
    def acquire(self, github_url: str) -> Iterator[AcquiredRepository]:
        with tempfile.TemporaryDirectory(prefix="repolens-") as temporary_directory:
            checkout = Path(temporary_directory, "repository")
            self._run(
                [
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--filter=blob:none",
                    "--no-tags",
                    "--no-recurse-submodules",
                    github_url,
                    str(checkout),
                ]
            )
            self._checkout_size(checkout)
            branch = self._run(["symbolic-ref", "--short", "HEAD"], cwd=checkout)
            commit_sha = self._run(["rev-parse", "HEAD"], cwd=checkout).lower()
            if not branch or not SHA_PATTERN.fullmatch(commit_sha):
                raise RepositoryAcquisitionError("Git returned invalid snapshot metadata")
            yield AcquiredRepository(path=checkout, branch=branch, commit_sha=commit_sha)
