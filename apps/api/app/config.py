from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALINEA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./.data/alinea.db"
    storage_root: Path = Path(".data/storage")
    redis_url: str = ""
    local_workers: int = Field(default=2, ge=1)
    soffice_path: Path | None = None
    render_timeout_seconds: int = Field(default=120, gt=0)
    max_file_mb: int = Field(default=15, gt=0)
    max_pages: int = Field(default=60, ge=1)
    project_ttl_hours: int = Field(default=24, gt=0)
    llm_base_url: str = "https://api.kimi.com/coding/"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "kimi-for-coding"
    llm_timeout_seconds: int = Field(default=180, gt=0)
    web_origins: Annotated[list[str], NoDecode] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]

    @field_validator("storage_root", mode="before")
    @classmethod
    def resolve_storage_root(cls, value: Any) -> Path:
        return _resolve_path(value)

    @field_validator("soffice_path", mode="before")
    @classmethod
    def resolve_soffice_path(cls, value: Any) -> Path | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return _resolve_path(value)

    @field_validator("web_origins", mode="before")
    @classmethod
    def parse_web_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def _resolve_path(value: Any) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


_runtime_settings: Settings | None = None


@lru_cache
def get_settings() -> Settings:
    return _runtime_settings if _runtime_settings is not None else Settings()


def configure_runtime_settings(settings: Settings | None) -> Settings | None:
    global _runtime_settings
    previous = _runtime_settings
    _runtime_settings = settings
    get_settings.cache_clear()
    return previous
