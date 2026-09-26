import re
import uuid
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.repository import RepositoryStatus

GITHUB_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class RepositorySubmission(BaseModel):
    github_url: str = Field(
        min_length=1,
        max_length=2048,
        examples=["https://github.com/openai/openai-python"],
    )

    @field_validator("github_url")
    @classmethod
    def validate_public_github_url(cls, value: str) -> str:
        candidate = value.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme != "https" or parsed.hostname is None:
            raise ValueError("repository URL must use HTTPS")
        if parsed.hostname.lower() != "github.com" or parsed.port is not None:
            raise ValueError("repository URL must be hosted on github.com")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("repository URL must not include credentials, a query, or a fragment")

        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) != 2:
            raise ValueError("repository URL must identify exactly one owner and repository")
        owner, name = parts
        if name.endswith(".git"):
            name = name[:-4]
        if not owner or not name or not all(
            GITHUB_COMPONENT_PATTERN.fullmatch(component) for component in (owner, name)
        ):
            raise ValueError("repository owner and name contain invalid characters")

        return urlunsplit(("https", "github.com", f"/{owner}/{name}", "", ""))


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    github_url: str
    owner: str
    name: str
    status: RepositoryStatus
    ingestion_error: str | None
    created_at: datetime
    updated_at: datetime

