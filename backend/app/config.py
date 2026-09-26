from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, configurable with REPOLENS_ environment variables."""

    app_name: str = "RepoLens API"
    environment: str = "development"
    debug: bool = False
    database_url: str = "sqlite:///./repolens.db"
    cors_origins: str = "http://localhost:5173"
    ingestion_include_globs: str = "*.py"
    ingestion_exclude_globs: str = ""
    ingestion_exclude_directories: str = (
        ".git,.hg,.svn,.venv,venv,node_modules,__pycache__,build,dist,.tox,.nox"
    )
    ingestion_max_files: int = Field(default=2_500, ge=1)
    ingestion_max_total_bytes: int = Field(default=25_000_000, ge=1)
    ingestion_max_file_bytes: int = Field(default=1_000_000, ge=1)
    ingestion_max_clone_bytes: int = Field(default=250_000_000, ge=1)
    ingestion_clone_timeout_seconds: int = Field(default=120, ge=1)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "repolens_code_units"
    embedding_provider: str = "hashing"
    embedding_dimensions: int = Field(default=384, ge=16, le=4_096)
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    retrieval_max_unit_chars: int = Field(default=12_000, ge=256)
    retrieval_max_units_per_snapshot: int = Field(default=20_000, ge=1)
    retrieval_lexical_candidate_limit: int = Field(default=5_000, ge=1)
    retrieval_hybrid_rrf_k: int = Field(default=60, ge=1)
    graph_source_roots: str = "src"

    model_config = SettingsConfigDict(
        env_prefix="REPOLENS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @staticmethod
    def _split_csv(value: str) -> tuple[str, ...]:
        return tuple(item.strip() for item in value.split(",") if item.strip())

    @property
    def ingestion_include_patterns(self) -> tuple[str, ...]:
        return self._split_csv(self.ingestion_include_globs)

    @property
    def ingestion_exclude_patterns(self) -> tuple[str, ...]:
        return self._split_csv(self.ingestion_exclude_globs)

    @property
    def ingestion_excluded_directory_names(self) -> frozenset[str]:
        return frozenset(self._split_csv(self.ingestion_exclude_directories))

    @property
    def graph_source_root_names(self) -> tuple[str, ...]:
        return self._split_csv(self.graph_source_roots)


@lru_cache
def get_settings() -> Settings:
    return Settings()
