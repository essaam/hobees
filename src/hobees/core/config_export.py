"""The active configuration as an importable document.

Both the Web UI YAML editor and the Studio Containers tab need the same thing: the
configuration the user is happy with right now, as providers/bees/hives/skills/memory.
Reading it from the ORM in one place keeps the YAML view and the generated
`hobees.yaml` identical, and keeps secrets out of it — providers store the *name* of
the environment variable, never the key.
"""

from __future__ import annotations

from typing import Any

import yaml

from hobees.db.models import Bee, Hive, LLMProvider, Memory, Skill
from hobees.db.session import session_scope

__all__ = ["config_document", "config_yaml"]


def config_document() -> dict[str, Any]:
    """Read the current registry into a plain dict shaped like an import file."""
    with session_scope() as session:
        providers = session.query(LLMProvider).order_by(LLMProvider.alias).all()
        bees = session.query(Bee).order_by(Bee.name).all()
        hives = session.query(Hive).order_by(Hive.name).all()
        skills = session.query(Skill).order_by(Skill.name).all()
        memories = session.query(Memory).order_by(Memory.namespace, Memory.key).all()

        document: dict[str, Any] = {
            "providers": [
                {
                    "alias": p.alias,
                    "provider_type": p.provider_type,
                    **({"base_url": p.base_url} if p.base_url else {}),
                    "api_key_env": p.api_key_env or "NONE",
                    **({"default_model": p.default_model} if p.default_model else {}),
                    **({"assistant_model": p.assistant_model} if getattr(p, "assistant_model", None) else {}),
                    "input_cost_per_1m": float(p.input_cost_per_1m or 0.0),
                    "output_cost_per_1m": float(p.output_cost_per_1m or 0.0),
                    "context_window_tokens": p.context_window_tokens or 128000,
                }
                for p in providers
            ],
            "bees": [
                {
                    "name": b.name,
                    "role_description": b.role_description,
                    "system_prompt": b.system_prompt or "",
                    "provider": b.provider.alias if b.provider else None,
                    "model": b.model_name,
                    "temperature": float(b.temperature or 0.0),
                    "thinking_level": b.thinking_level or "off",
                    "tools": list(b.tool_names or []),
                    "require_approval": list(b.require_approval or []),
                }
                for b in bees
            ],
            "hives": [
                {
                    "name": h.name,
                    **({"goal_description": h.goal_description} if h.goal_description else {}),
                    "supervisor_provider": h.supervisor_provider.alias if h.supervisor_provider else None,
                    "supervisor_model": h.supervisor_model_name,
                    **({"supervisor_prompt": h.supervisor_prompt} if h.supervisor_prompt else {}),
                    "supervisor_thinking_level": h.supervisor_thinking_level or "medium",
                    "is_dynamic": bool(h.is_dynamic),
                    **({"project_path": h.project_path} if h.project_path else {}),
                    "bees": [m.bee.name for m in (h.memberships or []) if m.bee],
                }
                for h in hives
            ],
        }

        if skills:
            document["skills"] = [
                {
                    "name": s.name,
                    "description": s.description,
                    "instructions": s.instructions,
                    "tags": list(s.tags or []),
                    "bees": [b.name for b in (s.bees or [])],
                }
                for s in skills
            ]
        if memories:
            document["memory"] = [
                {
                    "namespace": m.namespace,
                    "key": m.key,
                    "content": m.content,
                }
                for m in memories
            ]

        return document


def config_yaml(document: dict[str, Any] | None = None) -> str:
    """The same document as YAML text, ready to write to `hobees.yaml`."""
    return yaml.safe_dump(document if document is not None else config_document(), sort_keys=False, allow_unicode=True)


def has_config(document: dict[str, Any]) -> bool:
    """True when the document holds at least one entity worth shipping."""
    return any(bool(document.get(section)) for section in ("providers", "bees", "hives", "skills", "memory"))
