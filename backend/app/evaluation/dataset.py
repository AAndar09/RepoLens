import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.routing.service import QueryCategory, RouteStrategy
from app.schemas.investigation import ToolName
from app.schemas.repository import RepositorySubmission

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedRouting(EvaluationModel):
    category: QueryCategory
    strategy: RouteStrategy


class EvaluationCase(EvaluationModel):
    id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=3, max_length=2_000)
    question_type: str = Field(min_length=1, max_length=100)
    retrieval: bool = True
    expected_files: list[str] = Field(default_factory=list)
    expected_symbols: list[str] = Field(default_factory=list)
    symbol_query: str | None = Field(default=None, min_length=1, max_length=2_048)
    expected_routing: ExpectedRouting | None = None
    expected_tools: list[ToolName] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("case id must contain only lowercase letters, numbers, '.', '_', '-'")
        return value

    @field_validator("expected_files")
    @classmethod
    def validate_files(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            path = value.strip().replace("\\", "/")
            if not path or path.startswith("/") or ".." in path.split("/"):
                raise ValueError("expected files must be safe repository-relative paths")
            normalized.append(path)
        if len(normalized) != len(set(normalized)):
            raise ValueError("expected files must be unique")
        return normalized

    @field_validator("expected_symbols")
    @classmethod
    def validate_symbols(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("expected symbols must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("expected symbols must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_retrieval_targets(self) -> "EvaluationCase":
        if self.retrieval and not (self.expected_files or self.expected_symbols):
            raise ValueError("retrieval cases require at least one expected file or symbol")
        if self.symbol_query and not self.expected_symbols:
            raise ValueError("symbol_query requires expected_symbols")
        return self


class RepositoryCases(EvaluationModel):
    repository: str
    commit: str
    cases: list[EvaluationCase] = Field(min_length=1)

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        return RepositorySubmission(github_url=value).github_url

    @field_validator("commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SHA_PATTERN.fullmatch(normalized):
            raise ValueError("commit must be a full 40-character lowercase Git SHA")
        return normalized

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> "RepositoryCases":
        identifiers = [case.id for case in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("case ids must be unique within a repository")
        return self

    @property
    def owner_and_name(self) -> tuple[str, str]:
        owner, name = urlsplit(self.repository).path.strip("/").split("/")
        return owner, name


class EvaluationDataset(EvaluationModel):
    schema_version: int = Field(ge=1)
    dataset_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2_000)
    repositories: list[RepositoryCases] = Field(min_length=1)

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(
                "dataset id must contain only lowercase letters, numbers, '.', '_', '-'"
            )
        return value

    @model_validator(mode="after")
    def validate_unique_repositories(self) -> "EvaluationDataset":
        identities = [(*item.owner_and_name, item.commit) for item in self.repositories]
        if len(identities) != len(set(identities)):
            raise ValueError("repository/commit entries must be unique")
        case_ids = [case.id for item in self.repositories for case in item.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case ids must be unique across the dataset")
        return self


def load_dataset(path: Path) -> tuple[EvaluationDataset, str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    return EvaluationDataset.model_validate(payload), hashlib.sha256(raw).hexdigest()
