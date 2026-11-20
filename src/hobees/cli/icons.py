"""Icon & ASCII fallback registry for the hobees terminal UX.

Provides high-contrast Unicode/emoji icons with automatic ASCII fallback when
``NO_COLOR=1`` is set or the terminal stdout encoding is not UTF-8 (Section 3.2).
"""

from __future__ import annotations

import os
import sys


def _supports_unicode() -> bool:
    """Return True if the terminal can render Unicode/emoji icons."""
    if os.environ.get("NO_COLOR") == "1":
        return False
    if os.environ.get("HOBEE_ASCII") == "1":
        return False
    encoding = getattr(sys.stdout, "encoding", None) or ""
    try:
        "🍯".encode(encoding or "utf-8")
    except (LookupError, UnicodeEncodeError):
        return False
    return True


_USE_UNICODE = _supports_unicode()


def _icon(unicode_variant: str, ascii_variant: str) -> str:
    return unicode_variant if _USE_UNICODE else ascii_variant


# Application / prompt
APP = _icon("🍯", "[hobees]")

# Worker Bee (bot)
BEE = _icon("🐝", "[BEE]")

# Working Hive (team)
HIVE = _icon("⬡", "[HIVE]")

# Queen Meta-Orchestrator
QUEEN = _icon("👑", "[QUEEN]")

# LLM Provider
PROVIDER = _icon("🔌", "[LLM]")

# Tool execution
TOOL = _icon("🛠️", "[TOOL]")

# Usage / telemetry
USAGE = _icon("📊", "[STAT]")

# Active / running
ACTIVE = _icon("⚡", "[RUN]")

# Success / complete
SUCCESS = _icon("✅", "[OK]")

# Warning / error
WARN = _icon("⚠️", "[WARN]")
ERROR = _icon("❌", "[ERR]")

# v1.1 additions
# Long-Term Memory
MEMORY = _icon("🧠", "[MEM]")

# Skill / Honeycomb
SKILL = _icon("📜", "[SKILL]")

# Context Compaction
COMPACT = _icon("🗜️", "[COMP]")

# Thinking / Reasoning
THINKING = _icon("💭", "[THINK]")


__all__ = [
    "APP",
    "BEE",
    "HIVE",
    "QUEEN",
    "PROVIDER",
    "TOOL",
    "USAGE",
    "ACTIVE",
    "SUCCESS",
    "WARN",
    "ERROR",
    "MEMORY",
    "SKILL",
    "COMPACT",
    "THINKING",
    "supports_unicode",
]


def supports_unicode() -> bool:
    """Public helper exposing whether Unicode icons are active."""
    return _USE_UNICODE