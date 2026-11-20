"""Two-Tier Memory Management (FR-10).

* Short-Term Memory: Handled by LangGraph's PostgresSaver (thread_id checkpoints)
* Long-Term Scoped Memory: PostgreSQL 'memories' table with namespaces:
  - 'global' — user preferences, facts across all sessions
  - 'hive:<hive_name>' — project-specific context shared within a hive
  - 'bee:<bee_name>' — bee-specific learned patterns
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from hobees.config import settings
from hobees.db.session import session_scope
from hobees.db.models import LLMProvider, Memory

logger = logging.getLogger(__name__)

_AUTO_MEMORY_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z")
_SENSITIVE_MEMORY_VALUE = re.compile(
    r"(?i)(?:\b(?:api[_-]?key|access[_-]?token|password|passwd|secret|credential)\b"
    r"\s*[:=]\s*\S+|\bBearer\s+\S+|\b(?:sk-[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b)"
)
_AUTO_MEMORY_MAX_ITEMS = 8
_AUTO_MEMORY_MAX_CONTENT_CHARS = 1000


def get_memories_for_namespaces(namespaces: list[str]) -> list[dict]:
    """Retrieve memories matching the given namespaces."""
    if not namespaces:
        return []
    with session_scope() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.namespace.in_(namespaces))
            .order_by(Memory.updated_at.desc())
            .all()
        )
        return [
            {
                "namespace": r.namespace,
                "key": r.key,
                "content": r.content,
                "source_thread_id": r.source_thread_id,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


def upsert_memory(
    namespace: str,
    key: str,
    content: str,
    source_thread_id: str | None = None,
) -> None:
    """Insert or update a memory entry."""
    with session_scope() as session:
        mem = (
            session.query(Memory)
            .filter_by(namespace=namespace, key=key)
            .first()
        )
        if mem:
            mem.content = content
            mem.source_thread_id = source_thread_id
        else:
            mem = Memory(
                namespace=namespace,
                key=key,
                content=content,
                source_thread_id=source_thread_id,
            )
            session.add(mem)


def delete_memory(namespace: str, key: str) -> bool:
    """Delete a memory entry. Returns True if deleted."""
    with session_scope() as session:
        deleted = (
            session.query(Memory)
            .filter_by(namespace=namespace, key=key)
            .delete()
        )
        return deleted > 0


def list_memories(namespace: str | None = None) -> list[dict]:
    """List all memories, optionally filtered by namespace prefix."""
    with session_scope() as session:
        query = session.query(Memory).order_by(Memory.namespace, Memory.key)
        if namespace:
            query = query.filter(Memory.namespace.like(f"{namespace}%"))
        rows = query.all()
        return [
            {
                "namespace": r.namespace,
                "key": r.key,
                "content": r.content,
                "source_thread_id": r.source_thread_id,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


def build_memory_block(namespaces: list[str]) -> str:
    """Format memories for injection into system prompts."""
    memories = get_memories_for_namespaces(namespaces)
    if not memories:
        return ""

    lines = ["## Long-Term Memory (cross-session)"]
    for mem in memories:
        lines.append(f"- [{mem['namespace']}] {mem['key']}: {mem['content']}")
    return "\n".join(lines)


def extract_namespaces(
    global_: bool = True,
    hive_name: str | None = None,
    bee_name: str | None = None,
) -> list[str]:
    """Build the list of namespaces to query for a given context."""
    namespaces = []
    if global_:
        namespaces.append("global")
    if hive_name:
        namespaces.append(f"hive:{hive_name}")
    if bee_name:
        namespaces.append(f"bee:{bee_name}")
    return namespaces


def extract_run_memories(
    *,
    goal: str,
    output: str,
    provider: LLMProvider,
    model_name: str,
    hive_name: str,
    source_thread_id: str,
    allow_hive_facts: bool,
) -> int:
    """Extract opt-in durable memories from a completed Hive run."""
    if not settings.enable_auto_memory or not output.strip():
        return 0

    hive_scope_instruction = (
        f'For durable facts specific to the "{hive_name}" project, use scope "hive".'
        if allow_hive_facts
        else 'Only use scope "global"; this Hive is ephemeral and project facts will not persist usefully.'
    )
    prompt = f"""Extract at most {_AUTO_MEMORY_MAX_ITEMS} durable memories from this completed task.

Return ONLY a JSON array. Each item must have:
{{"key": "short_snake_case_key", "content": "concise fact", "scope": "global" or "hive"}}

Use "global" only for stable user preferences that apply across projects.
{hive_scope_instruction}
Do not store secrets, credentials, personal sensitive data, transient task details,
speculation, or facts that are only useful for this one task. Do not infer facts.
Return [] if there is nothing durable to remember.

Goal:
{goal[:2000]}

Final result:
{output[:6000]}"""

    try:
        from hobees.core.llm_factory import get_chat_model

        model = get_chat_model(provider, model_name, 0.0)
        response = model.invoke(prompt)
    except Exception:
        logger.exception("Automatic memory extraction failed for thread %s", source_thread_id)
        return 0

    response_text = str(getattr(response, "content", response)).strip()
    try:
        candidates = json.loads(response_text)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response_text, re.DOTALL)
        if not fenced:
            logger.warning(
                "Automatic memory extraction returned invalid JSON for thread %s",
                source_thread_id,
            )
            return 0
        try:
            candidates = json.loads(fenced.group(1))
        except json.JSONDecodeError:
            logger.warning(
                "Automatic memory extraction returned invalid JSON for thread %s",
                source_thread_id,
            )
            return 0

    if not isinstance(candidates, list):
        logger.warning(
            "Automatic memory extraction returned a non-list result for thread %s",
            source_thread_id,
        )
        return 0

    saved = 0
    for candidate in candidates[:_AUTO_MEMORY_MAX_ITEMS]:
        if not isinstance(candidate, dict):
            continue
        key = candidate.get("key")
        content = candidate.get("content")
        scope = candidate.get("scope")
        if (
            not isinstance(key, str)
            or not _AUTO_MEMORY_KEY.fullmatch(key)
            or re.search(
                r"(?:api[_-]?key|token|password|passwd|secret|credential)",
                key,
                re.IGNORECASE,
            )
            or not isinstance(content, str)
            or not content.strip()
            or len(content) > _AUTO_MEMORY_MAX_CONTENT_CHARS
            or _SENSITIVE_MEMORY_VALUE.search(content)
        ):
            continue
        if scope == "global":
            namespace = "global"
        elif scope == "hive" and allow_hive_facts:
            namespace = f"hive:{hive_name}"
        else:
            continue

        try:
            upsert_memory(namespace, key, content.strip(), source_thread_id)
        except Exception:
            logger.exception(
                "Could not save an automatically extracted memory for thread %s",
                source_thread_id,
            )
            continue
        saved += 1

    if saved:
        logger.info(
            "Saved %d automatic memories for thread %s",
            saved,
            source_thread_id,
        )
    return saved


# Tool functions for Bees to use
from langchain_core.tools import tool


@tool
def save_memory(key: str, content: str, namespace: str = "global") -> str:
    """Save a fact or preference to long-term memory.

    Args:
        key: Short identifier (e.g., 'user_prefers_typescript')
        content: The fact/preference to remember
        namespace: 'global', 'hive:<name>', or 'bee:<name>'
    """
    # Validate namespace format
    valid_prefixes = ("global", "hive:", "bee:")
    if not any(namespace.startswith(p) for p in valid_prefixes):
        return f"ERROR: namespace must start with one of {valid_prefixes}"

    upsert_memory(namespace, key, content)
    return f"Memory saved: [{namespace}] {key} = {content[:100]}"


@tool
def recall_memory(key: str, namespace: str = "global") -> str:
    """Recall a specific memory entry."""
    with session_scope() as session:
        mem = session.query(Memory).filter_by(namespace=namespace, key=key).first()
    if not mem:
        return f"No memory found for [{namespace}] {key}"
    return mem.content


__all__ = [
    "get_memories_for_namespaces",
    "upsert_memory",
    "delete_memory",
    "list_memories",
    "build_memory_block",
    "extract_namespaces",
    "extract_run_memories",
    "save_memory",
    "recall_memory",
]