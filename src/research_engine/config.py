"""Configuration loader supporting YAML and environment variables."""

from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseModel):
    path: Path = Field(default=Path("data/research_engine.db"))


class LLMConfig(BaseModel):
    base_url: str = Field(default="http://localhost:5000/v1")
    api_key: str = Field(default="anything")
    model: str = Field(default="smart")
    timeout_seconds: float = Field(default=60.0)


class ApiServiceConfig(BaseModel):
    base_url: str
    email: str = Field(default="")
    api_key: str = Field(default="")
    rate_limit_per_second: float = Field(default=5.0)


class ApisConfig(BaseModel):
    openalex: ApiServiceConfig = Field(
        default_factory=lambda: ApiServiceConfig(
            base_url="https://api.openalex.org",
            rate_limit_per_second=10.0,
        )
    )
    crossref: ApiServiceConfig = Field(
        default_factory=lambda: ApiServiceConfig(
            base_url="https://api.crossref.org",
            rate_limit_per_second=10.0,
        )
    )
    semanticscholar: ApiServiceConfig = Field(
        default_factory=lambda: ApiServiceConfig(
            base_url="https://api.semanticscholar.org/graph/v1",
            rate_limit_per_second=1.0,
        )
    )
    unpaywall: ApiServiceConfig = Field(
        default_factory=lambda: ApiServiceConfig(
            base_url="https://api.unpaywall.org/v2",
            rate_limit_per_second=5.0,
        )
    )


class ZoteroConfig(BaseModel):
    data_dir: Path = Field(default_factory=lambda: Path("~/Zotero").expanduser())
    bibtex_export_dir: Path = Field(default=Path("data/zotero_exports"))

    @field_validator("data_dir", mode="after")
    @classmethod
    def _expand_data_dir(cls, v: Path) -> Path:
        return v.expanduser()


class RetrievalConfig(BaseModel):
    pdf_storage_dir: Path = Field(default=Path("data/pdfs"))
    max_pdf_size_mb: float = Field(default=50.0)


class AppConfig(BaseSettings):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    apis: ApisConfig = Field(default_factory=ApisConfig)
    zotero: ZoteroConfig = Field(default_factory=ZoteroConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)

    model_config = SettingsConfigDict(
        env_prefix="RESEARCH_ENGINE_",
        env_nested_delimiter="__",
        extra="ignore",
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(config_file: Path | str | None = None) -> AppConfig:
    """Load configuration from YAML file and apply environment variable overrides."""
    load_dotenv(dotenv_path=Path(".env"))
    yaml_dict: dict[str, Any] = {}

    path_to_try = Path(config_file) if config_file else Path("config.yaml")
    if path_to_try.is_file():
        try:
            with open(path_to_try, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    yaml_dict = loaded
        except Exception as e:
            raise RuntimeError(f"Error reading configuration file {path_to_try}: {e}") from e

    # Instantiate from env first
    env_instance = AppConfig()
    env_dict = env_instance.model_dump()

    # Deep merge yaml over defaults, but let explicitly set env override yaml
    merged = _deep_merge(env_dict, yaml_dict)

    # Allow environment variables with RESEARCH_ENGINE_ to have highest priority
    import os
    prefix = "RESEARCH_ENGINE_"
    for env_k, env_v in os.environ.items():
        if env_k.startswith(prefix):
            clean_k = env_k[len(prefix):].lower()
            parts = clean_k.split("__")
            d = merged
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = env_v

    return AppConfig(**merged)

