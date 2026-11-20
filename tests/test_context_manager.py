"""Unit tests for Context Efficiency Engine (FR-9)."""

import os
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

from hobees.core.context_manager import (
    truncate_tool_output,
    project_worker_context,
    compact_messages,
    estimate_tokens,
    MAX_TOOL_OUTPUT_CHARS,
)


def test_truncate_tool_output_short():
    short_text = "Hello world"
    out = truncate_tool_output(short_text, call_id="c1", thread_id="t1")
    assert out == short_text


def test_truncate_tool_output_long(tmp_path):
    long_text = "A" * (MAX_TOOL_OUTPUT_CHARS + 500)
    out = truncate_tool_output(long_text, call_id="c2", thread_id="t2")
    assert len(out) < len(long_text)
    assert "[... OUTPUT TRUNCATED" in out
    assert "Full output saved to:" in out


def test_truncate_tool_output_uses_hive_scratchpad_root(tmp_path):
    long_text = "A" * (MAX_TOOL_OUTPUT_CHARS + 500)

    out = truncate_tool_output(
        long_text,
        call_id="c3",
        thread_id="t3",
        scratchpad_root=tmp_path / "scratchpad",
    )

    assert "scratchpad/t3/c3.txt" in out
    assert (
        tmp_path / "scratchpad" / "t3" / "c3.txt"
    ).read_text(encoding="utf-8") == long_text


def test_project_worker_context():
    ctx = project_worker_context(
        bee_name="coder",
        bee_role="Writes Python code",
        bee_system_prompt="Be concise",
        bee_skills=[{"name": "pytest-expert", "description": "Writes tests"}],
        memories=[{"namespace": "global", "key": "lang", "content": "Python"}],
        running_summary="Prior discussion on DB schema",
        subtask="Write test for user auth",
    )
    assert "# System Prompt" in ctx
    assert "Be concise" in ctx
    assert "# Your Role" in ctx
    assert "Writes Python code" in ctx
    assert "pytest-expert" in ctx
    assert "[global] lang: Python" in ctx
    assert "Prior discussion on DB schema" in ctx
    assert "Write test for user auth" in ctx


def test_compact_messages_under_threshold():
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    kept, summary = compact_messages(messages, context_window=100000)
    assert kept == messages
    assert summary == ""


def test_compact_messages_over_threshold():
    # Construct enough characters to exceed threshold
    messages = [
        {"role": "user", "content": f"Turn {i}: " + ("x" * 200)}
        for i in range(10)
    ]
    # Very small context window so it triggers compaction
    kept, summary = compact_messages(messages, context_window=500)
    assert len(kept) == 4
    assert "Summary of earlier conversation:" in summary
    assert "Turn 0" in summary


def test_compact_messages_with_langchain_objects():
    messages = [
        HumanMessage(content=f"User turn {i}: " + ("abc " * 50))
        for i in range(8)
    ]
    kept, summary = compact_messages(messages, context_window=500)
    assert len(kept) == 4
    assert isinstance(kept[0], HumanMessage)
    assert summary != ""


def test_estimate_tokens():
    assert estimate_tokens("12345678") == 2
