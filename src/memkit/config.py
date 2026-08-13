"""Settings, read once from the environment."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

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

    api_key: str = "change-me"
    api_key_file: Path | None = None
    telemetry_hmac_key: str = ""
    telemetry_retention_days: int = 90
    # Read unprefixed: the SDKs and every other tool expect these exact names.
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    # Gemini through either the Developer API or Vertex AI:
    #
    #   Gemini Developer API (the default): an API key alone. No GCP project,
    #     gcloud, or ADC. A plain AI Studio key works.
    #   Standard Vertex: project + location, using ADC or a key. Only needed for
    #     full GCP integration.
    #
    # Key precedence matches the areeza reference app so one key in the
    # environment serves both projects.
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_VERTEX_API_KEY"),
    )
    vertex_project: str = Field(
        default="",
        validation_alias=AliasChoices("VERTEX_PROJECT", "GOOGLE_CLOUD_PROJECT"),
    )
    vertex_location: str = Field(default="", validation_alias="VERTEX_LOCATION")
    owner_id: str = "u-1"
    owner_name: str = "owner"

    db_path: Path = Path("./data/memkit.db")
    qdrant_url: str = "http://127.0.0.1:6333"

    embed_model: str = "BAAI/bge-m3"
    embed_device: str = "mps"
    embed_revision: str = "5617a9f61b028005a4858fdac845db406aefb181"

    host: str = "127.0.0.1"
    port: int = 8077
    ui_dir: Path = Path(__file__).resolve().parent / "web_dist"
    cors_origins: list[str] = []
    expose_docs: bool = True
    allow_remote: bool = False
    export_dir: Path = Path("./data/exports")
    backup_dir: Path = Path("./data/backups")
    qdrant_version: str = "1.18.2"

    monthly_cost_limit_usd: float = 15.0
    improvement_budget_usd: float = 10.0

    # Cheapest option. Swap for a claude-* model to compare on the same eval;
    # see providers.py.
    judge_model: str = "gemini-3.5-flash-lite"

    # Read-path dedup threshold. Kept at the documented 0.90, but exposed as a
    # setting so it can be swept by the eval rather than edited in code.
    # Measured on BGE-M3 with this corpus: an exact restatement scores 1.0000,
    # a genuine paraphrase of the same fact ("prefers pnpm over npm for all
    # projects" / "prefers pnpm rather than npm everywhere") only 0.8979, and
    # two distinct tool preferences ("pnpm" / "pytest") 0.7422. So 0.90 catches
    # near-verbatim duplicates only; somewhere near 0.85 would catch paraphrases
    # while still separating distinct facts. Decide it on the eval, not by feel.
    dedup_cosine: float = 0.90

    # Nightly consolidation (stage 4). Clustering is stricter than the read-path
    # dedup above: dedup only hides a duplicate from one answer, consolidation
    # rewrites the store, so a wrong merge is permanent where a wrong hide is not.
    # Measured on this corpus: a real duplicate pair ("User's name is Maga Luev" /
    # "User's name is Maga (or MagaLoviev)") sits at 0.9278, and the pair that must
    # never merge ("Prefers pnpm" / "Prefers pytest") at 0.7422. So the documented
    # 0.92 does catch this class. See decisions/0031.
    consolidate_cosine: float = 0.92
    # Facts not retrieved in this long lose importance on the nightly pass.
    consolidate_stale_days: int = 90
    consolidate_demotion: float = 0.1

    @model_validator(mode="after")
    def load_secret_files(self) -> Settings:
        if self.api_key_file is not None:
            path = self.api_key_file.expanduser()
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                raise ValueError(f"API key file permissions must be 0600: {path}")
            key = path.read_text(encoding="utf-8").strip()
            if len(key) < 32:
                raise ValueError("API key file must contain at least 32 characters")
            self.api_key = key
        if not self.telemetry_hmac_key:
            self.telemetry_hmac_key = self.api_key
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        _settings.backup_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(_settings.backup_dir, 0o700)
    return _settings
