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


@lru_cache
def get_settings() -> Settings:
    return Settings()
