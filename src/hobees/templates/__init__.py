"""Built-in starter blueprint templates for hobees.

Templates are minimal valid hobees.yaml files that can be scaffolded
with ``hobees init --template <name>``.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

_TEMPLATES_PKG = "hobees.templates"

AVAILABLE_TEMPLATES: dict[str, str] = {
    "code-review":    "Full code-review pipeline: OpenAI coder + Anthropic reviewer + planner",
    "research":       "Research team: searcher + synthesiser (OpenAI + Gemini)",
    "docs-writer":    "Documentation team: writer + editor (OpenAI)",
    "local-ollama":   "Local-only setup via Ollama (localhost:11434) — no API key needed",
    "local-llamacpp": "Local-only setup via llama-server / llama.cpp (localhost:8080) — no API key needed",
}

_FILE_NAMES: dict[str, str] = {
    "code-review":    "code_review.yaml",
    "research":       "research.yaml",
    "docs-writer":    "docs_writer.yaml",
    "local-ollama":   "local_ollama.yaml",
    "local-llamacpp": "local_llamacpp.yaml",
}


def get_template_text(name: str) -> str:
    """Return the YAML text for a built-in template by name.

    Raises:
        KeyError: if the template name is not recognised.
        FileNotFoundError: if the template file is missing from the package.
    """
    if name not in _FILE_NAMES:
        raise KeyError(f"Unknown template {name!r}. Available: {list(AVAILABLE_TEMPLATES)}")

    filename = _FILE_NAMES[name]
    ref = importlib.resources.files(_TEMPLATES_PKG).joinpath(filename)
    return ref.read_text(encoding="utf-8")


__all__ = ["AVAILABLE_TEMPLATES", "get_template_text"]
