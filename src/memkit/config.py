"""Settings, read once from the environment."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "memkit"
DEFAULT_DATA_DIR = (
    Path.home() / "Library" / "Application Support" / "memkit"
    if sys.platform == "darwin"
    else Path.home() / ".local" / "share" / "memkit"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(DEFAULT_CONFIG_DIR / "config.env", ".env"),
        env_prefix="MEMKIT_",
        extra="ignore",
    )

    # Postgres is the source of truth. No default: pointing a team instance at
    # the wrong database silently is worse than refusing to start.
    database_url: str = ""
    database_pool_max: int = 10

    # Signs nothing by itself, but every stored query identity is HMAC'd with
    # it, so rotating it retires old telemetry rather than exposing queries.
    telemetry_hmac_key: str = ""
    telemetry_retention_days: int = 90

    # Read unprefixed: the SDKs and every other tool expect these exact names.
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    # Optional semantic judgments. Merely configuring a key enables no calls.
    jev_api_key: str = Field(
        default="", validation_alias=AliasChoices("JEV", "TYPESAFE_API_KEY"), repr=False
    )
    jev_model: str = "jev-1.13.0"
    semantic_version: Literal["v1", "v2", "v3", "v4"] = "v2"
    semantic_dedup: Literal["off", "shadow", "verify"] = "off"
    semantic_retrieval: Literal["off", "shadow", "rerank", "filter", "contribution"] = "off"
    semantic_support: Literal["off", "shadow"] = "off"
    # Applies only when a caller explicitly requests include_raw. Original
    # user passages and facts then share one selection and one token budget.
    semantic_context: Literal["off", "select", "compact"] = "off"
    semantic_contribution_floor: float = Field(default=0.7, ge=0, le=1)
    semantic_redundancy_floor: float = Field(default=0.7, ge=0, le=1)
    semantic_timeout_seconds: float = Field(default=3, gt=0, le=20)
    semantic_duplicate_floor: float = Field(default=0.9, ge=0, le=1)
    semantic_relevance_floor: float = Field(default=2.0, ge=0, le=3)

    # Gemini through either the Developer API or Vertex AI:
    #
    #   Gemini Developer API (the default): an API key alone. No GCP project,
    #     gcloud, or ADC. A plain AI Studio key works.
    #   Standard Vertex: project + location, using ADC or a key.
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_VERTEX_API_KEY"),
    )
    vertex_project: str = Field(
        default="",
        validation_alias=AliasChoices("VERTEX_PROJECT", "GOOGLE_CLOUD_PROJECT"),
    )
    vertex_location: str = Field(default="", validation_alias="VERTEX_LOCATION")

    # The shared scope every user belongs to, created on first start.
    team_name: str = "Team"

    # Dashboard sessions. Secure is on by default because the deployment target
    # terminates TLS in front of the app; a plain local HTTP run turns it off.
    cookie_secure: bool = True
    session_ttl_days: int = 14

    qdrant_url: str = "http://127.0.0.1:6333"

    embed_model: str = "BAAI/bge-m3"
    # Apple Silicon has Metal; a Linux container almost never has a GPU, and
    # asking for one that is absent costs a warning and a fallback on every boot.
    embed_device: str = "mps" if sys.platform == "darwin" else "cpu"
    embed_revision: str = "5617a9f61b028005a4858fdac845db406aefb181"
    # Vector width must match the Qdrant collection: changing the model means a
    # reindex, which is why the width is configuration rather than a constant.
    embed_dim: int = 1024
    embed_backend: str = "local"

    host: str = "127.0.0.1"
    port: int = 8077
    ui_dir: Path = Path(__file__).resolve().parent / "web_dist"
    cors_origins: list[str] = []
    expose_docs: bool = True
    allow_remote: bool = False
    export_dir: Path = DEFAULT_DATA_DIR / "exports"
    backup_dir: Path = DEFAULT_DATA_DIR / "backups"
    qdrant_version: str = "1.18.2"

    monthly_cost_limit_usd: float = 15.0
    improvement_budget_usd: float = 10.0

    # Cheapest option. Swap for a claude-* model to compare on the same eval;
    # see providers.py.
    judge_model: str = "gemini-3.5-flash-lite"

    # Write-time dedup threshold on the extraction path (decisions/0055): an ADD
    # whose text is closer than this to an existing active memory in the same
    # scope links its evidence to that memory instead of inserting a twin.
    # Manual writes are never deduplicated semantically. Measured on BGE-M3 with
    # this corpus: an exact restatement scores 1.0000, a genuine paraphrase of
    # the same fact only 0.8979, and two distinct tool preferences 0.7422. So
    # 0.90 catches near-verbatim duplicates only; decide it on the eval.
    dedup_cosine: float = 0.90

    # Nightly consolidation. Clustering is stricter than the write-time dedup
    # above: dedup only stops one new twin at write time, consolidation rewrites
    # the store, so a wrong merge is permanent where a skipped insert loses
    # nothing but a duplicate.
    consolidate_cosine: float = 0.92
    consolidate_stale_days: int = 90
    consolidate_demotion: float = 0.1
    # Decay stops here. Without a floor, a fact nobody happened to retrieve lost
    # importance every pass until it reached zero, which drops it below every
    # other memory in the profile ordering and removes its retrieval bonus.
    consolidate_importance_floor: float = 0.3

    # Optional cross-encoder rerank. Empty means off; see rerank.py.
    rerank_model: str = ""

    @model_validator(mode="after")
    def derive_secrets(self) -> Settings:
        if not self.telemetry_hmac_key:
            key_file = DEFAULT_CONFIG_DIR / "telemetry-key"
            if key_file.is_file():
                mode = stat.S_IMODE(key_file.stat().st_mode)
                if mode & 0o077:
                    raise ValueError(f"key file permissions must be 0600: {key_file}")
                self.telemetry_hmac_key = key_file.read_text(encoding="utf-8").strip()
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        for directory in (_settings.export_dir, _settings.backup_dir):
            directory.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                os.chmod(directory, 0o700)
    return _settings


def reset_settings() -> None:
    """Drop the cached settings. Tests and `memkit setup` only."""
    global _settings
    _settings = None
