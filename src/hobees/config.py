"""Application configuration loaded from ``~/.hobees/.env`` or local ``.env``.

Settings:
  HOBEES_DATABASE_URL        - database URL (PostgreSQL recommended; SQLite supported)
  HOBEES_QUEEN_PROVIDER      - default provider alias used by the Queen Meta-Orchestrator
  HOBEES_QUEEN_MODEL         - default model used by the Queen Meta-Orchestrator
  HOBEES_API_HOST            - local FastAPI bind host (default 127.0.0.1)
  HOBEES_API_PORT            - local FastAPI bind port (default 8420)
  HOBEES_LOG_LEVEL           - application log level
  HOBEES_COMPACTION_THRESHOLD - fraction of context window before compaction (default 0.65)
  HOBEES_MAX_TOOL_OUTPUT_CHARS - max chars for tool output before scratchpad offload (default 8000)
  HOBEES_ENABLE_AUTO_MEMORY   - enable automatic post-run memory extraction (default false)
  HOBEES_SKILLS_DIR           - directory for skill markdown files (default ~/.hobees/skills)
  HOBEES_TRACE_CONTENT_MODE - trace content level: metadata, summary, or full (default summary)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_DIR = Path.home() / ".hobees"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_CONFIG_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        env_prefix="HOBEES_",
        extra="ignore",
    )

    database_url: str | None = Field(
        default=None,
        description="PostgreSQL connection string (e.g. postgresql+psycopg://user:pass@localhost:5432/hobees)",
    )
    queen_provider: str = Field(default="openai", description="Default Queen provider alias")
    queen_model: str = Field(default="gpt-4o-mini", description="Default Queen model name")
    api_host: str = Field(default="127.0.0.1", description="FastAPI bind host")
    api_port: int = Field(default=8420, description="FastAPI bind port")
    log_level: str = Field(default="INFO", description="Application log level")

    compaction_threshold: float = Field(default=0.65, description="Fraction of context window before compaction")
    max_tool_output_chars: int = Field(default=8000, description="Max chars for tool output before scratchpad offload")
    enable_auto_memory: bool = Field(default=False, description="Enable automatic post-run memory extraction")
    skills_dir: Path = Field(default_factory=lambda: Path.home() / ".hobees" / "skills", description="Directory for skill markdown files")
    trace_content_mode: Literal["metadata", "summary", "full"] = Field(
        default="summary",
        description="Trace message content level: metadata, redacted summaries, or full redacted messages",
    )
    config_path: Path | None = Field(default=None, description="Path to declarative config YAML/JSON to auto-import")
    artifacts_root: Path = Field(default_factory=lambda: Path("./artifacts"), description="Default root directory for per-hive artifacts")


settings = Settings()

__all__ = ["Settings", "settings"]