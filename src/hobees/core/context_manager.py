"""Context Efficiency Engine (FR-9).

Implements four controls to prevent quadratic token growth:
1. Worker Context Isolation (State Projection)
2. Tool Output Truncation & Scratchpad Offloading
3. Rolling Conversation Compaction
4. Progressive Skill Loading
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from hobees.config import settings
from hobees.core.paths import safe_path_component

# Scratchpad directory for offloaded tool outputs
_SCRATCHPAD_ROOT = Path.home() / ".hobees" / "scratchpad"
_SCRATCHPAD_ROOT.mkdir(parents=True, exist_ok=True)

MAX_TOOL_OUTPUT_CHARS = settings.max_tool_output_chars
COMPACTION_THRESHOLD = settings.compaction_threshold


def truncate_tool_output(
    output: str,
    call_id: str,
    thread_id: str,
    scratchpad_root: Path | None = None,
) -> str:
    """Truncate tool output if it exceeds MAX_TOOL_OUTPUT_CHARS.

    Full output is written to a scratchpad file; a preview is returned.
    """
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output

    # Write full output to scratchpad. The thread key is namespaced (`:`), which
    # is not a legal path segment on Windows, so the directory and the path shown
    # to the model both use the same filesystem-safe form.
    scratch_root = scratchpad_root or _SCRATCHPAD_ROOT
    thread_dir = safe_path_component(thread_id)
    call_name = safe_path_component(call_id, separator="_")
    scratch_dir = scratch_root / thread_dir
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch_file = scratch_dir / f"{call_name}.txt"
    scratch_file.write_text(output, encoding="utf-8")
    display_path = (
        (Path("scratchpad") / thread_dir / scratch_file.name).as_posix()
        if scratchpad_root
        else scratch_file
    )

    # Return truncated preview with instructions
    half = MAX_TOOL_OUTPUT_CHARS // 2
    preview = (
        output[:half]
        + f"\n\n[... OUTPUT TRUNCATED ({len(output)} chars) ...]\n"
        f"Full output saved to: {display_path}\n"
        f"Use the 'read_file' tool with path '{display_path}' to view specific sections ...]"
        + output[-half:]
    )
    return preview


def project_worker_context(
    bee_name: str,
    bee_role: str,
    bee_system_prompt: str,
    bee_skills: list[dict] | None,
    memories: list[dict],
    running_summary: str | None,
    subtask: str,
) -> str:
    """Construct isolated context for a Worker Bee (State Projection).

    The worker does NOT receive the raw multi-turn supervisor message log.
    Instead, it gets a clean input containing only what it needs:
    - System prompt
    - Scoped memories (global + hive + bee)
    - Skill metadata headers (name + description only)
    - Running summary of prior steps
    - The specific subtask instruction
    """
    parts = []

    # System prompt
    parts.append(f"# System Prompt\n{bee_system_prompt}")

    # Role description
    parts.append(f"\n# Your Role\n{bee_role}")

    # Scoped memories
    if memories:
        parts.append("\n## Known Context & Preferences")
        for mem in memories:
            parts.append(f"- [{mem['namespace']}] {mem['key']}: {mem['content']}")

    # Skill metadata headers only (not full instructions)
    if bee_skills:
        parts.append("\n## Available Skills (use load_skill to read full instructions)")
        for skill in bee_skills:
            parts.append(f"- {skill['name']}: {skill['description']}")

    # Rolling summary
    if running_summary:
        parts.append(f"\n## Conversation Summary (prior steps)\n{running_summary}")

    # Current subtask
    parts.append(f"\n## Your Task\n{subtask}")

    return "\n".join(parts)


def compact_messages(
    messages: list[dict] | list[Any],
    context_window: int,
    summarizer_model: Any | None = None,
) -> tuple[list[Any], str]:
    """Compress older messages into a running summary.

    Uses langchain's trim_messages or standard extraction to keep the most
    recent messages verbatim and summarizes the rest. Returns (kept_messages, running_summary).
    Supports both dict representations and LangChain BaseMessage objects.
    """
    def _msg_content(m: Any) -> str:
        if isinstance(m, dict):
            return str(m.get("content", ""))
        return str(getattr(m, "content", ""))

    def _msg_role(m: Any) -> str:
        if isinstance(m, dict):
            return str(m.get("role", "unknown"))
        return getattr(m, "name", None) or type(m).__name__

    try:
        from langchain_core.messages import trim_messages, HumanMessage, AIMessage, SystemMessage
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        # Fallback: just keep last 4 messages
        kept = messages[-4:] if len(messages) > 4 else messages
        summary = "Previous context compacted (summarizer unavailable)."
        return kept, summary

    # Estimate tokens (rough: 4 chars per token)
    total_chars = sum(len(_msg_content(m)) for m in messages)
    estimated_tokens = total_chars // 4

    if estimated_tokens < context_window * COMPACTION_THRESHOLD:
        # No compaction needed
        return messages, ""

    # Keep last 4 messages verbatim
    keep_last = 4
    if len(messages) <= keep_last:
        return messages, ""

    recent = messages[-keep_last:]
    older = messages[:-keep_last]

    if not older:
        return messages, ""

    # Create a summarization prompt
    if summarizer_model is None:
        # Fast fallback: structured summary string
        summary_content = "Summary of earlier conversation:\n"
        for msg in older:
            role = _msg_role(msg)
            content = _msg_content(msg)[:500]
            summary_content += f"- {role}: {content}\n"
        return recent, summary_content

    # Use LLM to summarize
    try:
        older_text = "\n".join(
            f"{_msg_role(m)}: {_msg_content(m)[:200]}"
            for m in older
        )
        prompt = ChatPromptTemplate.from_template(
            "Summarize the following conversation concisely, preserving key facts, "
            "decisions, and pending tasks:\n\n{conversation}"
        )
        chain = prompt | summarizer_model
        summary_result = chain.invoke({"conversation": older_text})
        summary = getattr(summary_result, "content", str(summary_result))
    except Exception:
        summary = "Previous context compacted (summarization failed)."

    return recent, summary


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token."""
    return len(text) // 4


__all__ = [
    "truncate_tool_output",
    "project_worker_context",
    "compact_messages",
    "estimate_tokens",
    "MAX_TOOL_OUTPUT_CHARS",
    "COMPACTION_THRESHOLD",
]