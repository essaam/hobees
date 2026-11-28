"""Auto-detection of available LLM providers on first launch.

Scans environment variables and local TCP ports to identify providers the
user already has access to, without requiring any manual configuration.

The detection is intentionally fast:
  - Env-var checks are O(1) dict lookups.
  - Port probes use ``socket.create_connection`` with a 0.5 s timeout — no
    HTTP overhead, no SDK cold-start.

This module is called at most *once* per installation: ``main._root()``
writes a sentinel file (``~/.hobees/.detected``) after the first scan so
subsequent launches are not delayed. The Web UI can rerun it on demand from the
Providers tab, which is also where the catalog is read back by alias.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

_SENTINEL_FILE = Path.home() / ".hobees" / ".detected"

# ---------------------------------------------------------------------------
# Static provider catalogue
# ---------------------------------------------------------------------------

# Cloud providers: keyed by well-known env-var name.
_CLOUD_PROVIDERS: list[dict] = [
    {
        "env_var": "OPENAI_API_KEY",
        "alias": "openai-main",
        "provider_type": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "input_cost_per_1m": 0.15,
        "output_cost_per_1m": 0.60,
        "context_window_tokens": 128000,
        "source_label": "env:OPENAI_API_KEY",
    },
    {
        "env_var": "ANTHROPIC_API_KEY",
        "alias": "anthropic-main",
        "provider_type": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-5-sonnet-20241022",
        "input_cost_per_1m": 3.00,
        "output_cost_per_1m": 15.00,
        "context_window_tokens": 200000,
        "source_label": "env:ANTHROPIC_API_KEY",
    },
    {
        "env_var": "GEMINI_API_KEY",
        "alias": "gemini-main",
        "provider_type": "google_genai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
        "input_cost_per_1m": 0.075,
        "output_cost_per_1m": 0.30,
        "context_window_tokens": 1048576,
        "source_label": "env:GEMINI_API_KEY",
    },
    {
        "env_var": "OPENROUTER_API_KEY",
        "alias": "openrouter-main",
        "provider_type": "openai_compatible",
        "api_key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
        "input_cost_per_1m": 0.15,
        "output_cost_per_1m": 0.60,
        "context_window_tokens": 128000,
        "source_label": "env:OPENROUTER_API_KEY",
    },
    {
        "env_var": "DEEPSEEK_API_KEY",
        "alias": "deepseek-main",
        "provider_type": "openai_compatible",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "input_cost_per_1m": 0.27,
        "output_cost_per_1m": 1.10,
        "context_window_tokens": 65536,
        "source_label": "env:DEEPSEEK_API_KEY",
    },
]

# Local providers: probed via fast TCP connect.
_LOCAL_PROVIDERS: list[dict] = [
    {
        "host": "localhost",
        "port": 11434,
        "alias": "ollama-local",
        "provider_type": "openai_compatible",
        "api_key_env": "NONE",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "input_cost_per_1m": 0.0,
        "output_cost_per_1m": 0.0,
        "context_window_tokens": 128000,
        "source_label": "local:11434 (Ollama)",
    },
    {
        "host": "localhost",
        "port": 8080,
        "alias": "llamacpp-local",
        "provider_type": "openai_compatible",
        "api_key_env": "NONE",
        "base_url": "http://localhost:8080/v1",
        "default_model": "qwen2.5-coder-7b",
        "input_cost_per_1m": 0.0,
        "output_cost_per_1m": 0.0,
        "context_window_tokens": 32768,
        "source_label": "local:8080 (llama-server)",
    },
    {
        "host": "localhost",
        "port": 1234,
        "alias": "lmstudio-local",
        "provider_type": "openai_compatible",
        "api_key_env": "NONE",
        "base_url": "http://localhost:1234/v1",
        "default_model": "local-model",
        "input_cost_per_1m": 0.0,
        "output_cost_per_1m": 0.0,
        "context_window_tokens": 32768,
        "source_label": "local:1234 (LM Studio)",
    },
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_detection_spec(alias: str) -> dict | None:
    """Return the catalog entry for *alias* in the shape detection candidates use.

    Lets a caller register one named candidate without probing anything again.
    """
    for spec in _CLOUD_PROVIDERS + _LOCAL_PROVIDERS:
        if spec["alias"] == alias:
            return {
                key: value
                for key, value in spec.items()
                if key not in ("env_var", "host", "port")
            }
    return None


def is_first_launch() -> bool:
    """Return True if the first-launch wizard has never run on this machine."""
    return not _SENTINEL_FILE.exists()


def mark_detected() -> None:
    """Write the sentinel file so the wizard does not run again."""
    _SENTINEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SENTINEL_FILE.touch()


def detect_available_providers() -> list[dict]:
    """Scan env vars and local TCP ports for available LLM providers.

    Returns:
        List of provider candidate dicts, each containing the keys needed
        to register a provider via the DB directly.  May be empty if nothing
        is detected.

    Notes:
        This function is intentionally side-effect free — it does not write
        to the database or touch the filesystem (except reading env vars and
        probing TCP ports).
    """
    candidates: list[dict] = []

    # 1. Cloud providers: check env vars
    for spec in _CLOUD_PROVIDERS:
        if os.environ.get(spec["env_var"]):
            # Exclude the internal "env_var" key from the returned dict
            candidates.append({k: v for k, v in spec.items() if k != "env_var"})

    # 2. Local providers: fast TCP probe (0.5 s timeout per port)
    for spec in _LOCAL_PROVIDERS:
        if _port_open(spec["host"], spec["port"]):
            candidates.append({k: v for k, v in spec.items() if k not in ("host", "port")})

    return candidates


def auto_register_providers(
    candidates: list[dict],
    force: bool = False,
) -> list[str]:
    """Register detected provider candidates in the database.

    Args:
        candidates: List of dicts as returned by ``detect_available_providers``.
        force: If True, update existing rows instead of skipping them.

    Returns:
        List of alias strings that were actually registered (skips duplicates
        unless *force* is True).
    """
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider

    registered: list[str] = []

    with session_scope() as session:
        for spec in candidates:
            alias = spec["alias"]
            existing = session.query(LLMProvider).filter_by(alias=alias).first()

            if existing and not force:
                # Already registered — skip silently
                continue

            if existing:
                _apply_spec_to_row(existing, spec)
            else:
                row = LLMProvider(
                    alias=alias,
                    provider_type=spec["provider_type"],
                    api_key_env=spec.get("api_key_env", "NONE"),
                    base_url=spec.get("base_url"),
                    default_model=spec.get("default_model"),
                    input_cost_per_1m=spec.get("input_cost_per_1m", 0.0),
                    output_cost_per_1m=spec.get("output_cost_per_1m", 0.0),
                    context_window_tokens=spec.get("context_window_tokens", 128000),
                )
                session.add(row)

            registered.append(alias)

    return registered


def get_registered_provider_aliases() -> set[str]:
    """Return aliases already present in the provider registry."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider

    with session_scope() as session:
        return {
            alias
            for (alias,) in session.query(LLMProvider.alias).all()
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to *host*:*port* succeeds within *timeout* seconds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _apply_spec_to_row(row: object, spec: dict) -> None:
    """Update an existing ORM provider row with values from a spec dict."""
    row.provider_type = spec["provider_type"]
    row.api_key_env = spec.get("api_key_env", "NONE")
    row.base_url = spec.get("base_url")
    row.default_model = spec.get("default_model")
    row.input_cost_per_1m = spec.get("input_cost_per_1m", 0.0)
    row.output_cost_per_1m = spec.get("output_cost_per_1m", 0.0)
    row.context_window_tokens = spec.get("context_window_tokens", 128000)


__all__ = [
    "detect_available_providers",
    "auto_register_providers",
    "find_detection_spec",
    "get_registered_provider_aliases",
    "is_first_launch",
    "mark_detected",
]
