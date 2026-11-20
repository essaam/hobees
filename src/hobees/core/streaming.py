"""Shared helpers for consuming LangGraph ``astream`` / ``stream`` chunks.

In LangGraph 1.x the default ``stream_mode`` for ``astream`` / ``stream`` is
``"updates"``. In that mode each yielded chunk maps a node name to that
node's state update, e.g.::

    {"agent": {"messages": [AIMessage(...)]}}
    {"tools": {"messages": [ToolMessage(...), ...]}}

The interactive shell and TUI previously checked ``if "messages" in chunk``,
which is *never* true in updates mode, so no model output (thinking or the
final response) was ever rendered and no per-run telemetry was shown.
:func:`iter_chunk_messages` normalises every supported chunk shape into a flat
list of the newly-emitted messages regardless of stream mode.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "iter_chunk_messages",
    "message_content",
    "message_reasoning",
    "message_to_lines",
]


def _ensure_list(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _unwrap_prefixed(msg: Any) -> Any:
    """LangGraph may emit ``(id, message)`` pairs; unwrap to the message."""
    if isinstance(msg, tuple) and len(msg) == 2:
        return msg[1]
    return msg


def _is_message(obj: Any) -> bool:
    """Duck-type detection for any LangChain/LangGraph message object."""
    return hasattr(obj, "type") and hasattr(obj, "content")


def iter_chunk_messages(chunk: Any) -> list[Any]:
    """Return the newly-emitted messages contained in one ``astream`` chunk.

    Handles:
    * ``"values"`` mode chunks: ``{"messages": [...state...]}``
    * ``"updates"`` mode chunks: ``{node_name: {"messages": [...]}}`` or
      ``{node_name: [message, ...]}``
    * a single ``tuple[stream_mode, data]`` from multi-mode streams.
    """
    found: list[Any] = []

    def collect(value: Any) -> None:
        value = _unwrap_prefixed(value)
        if _is_message(value):
            found.append(value)
            return
        if isinstance(value, dict):
            msgs = value.get("messages")
            if isinstance(msgs, (list, tuple)):
                for item in msgs:
                    collect(item)
                return
            # A node-name -> node-update mapping (updates mode); recurse.
            for sub in value.values():
                collect(sub)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    # Multi-mode streams yield a (mode, data) tuple.
    if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], str):
        collect(chunk[1])
        return found

    collect(chunk)
    return found


def message_content(msg: Any) -> str:
    """Return the human-readable text content of a message as a ``str``.

    Some providers return ``content`` as a list of parts (e.g. OpenAI
    ``[{"type": "text", "text": "..."}]``); those are flattened to plain text.
    """
    content = getattr(msg, "content", "")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(content)


def message_reasoning(msg: Any) -> str:
    """Return reasoning/thinking text for a message when present."""
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        return str(reasoning)
    additional = getattr(msg, "additional_kwargs", None)
    if isinstance(additional, dict):
        for key in ("reasoning_content", "thinking", "reasoning", "reasoning_details"):
            value = additional.get(key)
            if value:
                return str(value)
    return ""


def _short(text: str, limit: int = 300) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def message_to_lines(msg: Any) -> list[tuple[str, str]]:
    """Convert a single message into ``(kind, text)`` display lines.

    ``kind`` is one of ``"thinking"``, ``"action"`` and ``"assistant"``:

    * ``"thinking"``  -- model reasoning/thinking text
    * ``"action"``    -- tool calls and tool results (compact)
    * ``"assistant"`` -- user-facing response text

    Returns an empty list when the message has nothing worth displaying.
    """
    lines: list[tuple[str, str]] = []

    tool_calls = getattr(msg, "tool_calls", None) or []
    for tc in tool_calls:
        name = tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, "name", "unknown")
        args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
        lines.append(("action", f"\U0001F527 {name}({str(args)[:80]})"))

    reasoning = message_reasoning(msg)
    if reasoning:
        lines.append(("thinking", f"\U0001F4AD {reasoning.strip()}"))

    mtype = getattr(msg, "type", "")
    text = message_content(msg)
    if text and text.strip():
        if mtype == "tool":
            label = getattr(msg, "name", None) or "tool"
            lines.append(("action", f"\U0001F4E4 {label}: {_short(text)}"))
        else:
            lines.append(("assistant", text.strip()))

    return lines

# ---------------------------------------------------------------------------
# Token-level streaming (``stream_mode="messages"``)
# ---------------------------------------------------------------------------

_THINKING_BLOCK_TYPES = ("thinking", "reasoning", "reasoning_content", "redacted_thinking")


def _stream_message(item: Any) -> Any:
    """Extract the message from a ``stream_mode="messages"`` stream item.

    Accepts ``(chunk, metadata)`` tuples, ``("messages", (chunk, metadata))``
    tuples from multi-mode streams, and bare messages.
    """
    if not isinstance(item, tuple):
        return item if _is_message(item) else None
    if len(item) == 2 and isinstance(item[0], str) and not _is_message(item[1]):
        return _stream_message(item[1])
    for part in item:
        if _is_message(part):
            return part
    return None


def _split_content_blocks(content: Any) -> tuple[str, str]:
    """Split content into ``(text, thinking)`` for list-of-block content.

    Anthropic/Gemini emit reasoning as ``{"type": "thinking", ...}`` blocks
    inside ``content`` rather than in ``additional_kwargs``.
    """
    if isinstance(content, str):
        return content, ""
    if not isinstance(content, (list, tuple)):
        return ("" if content is None else str(content)), ""

    text_parts: list[str] = []
    think_parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            text_parts.append(block)
        elif isinstance(block, dict):
            btype = str(block.get("type", ""))
            if btype in _THINKING_BLOCK_TYPES:
                val = block.get("thinking") or block.get("reasoning") or block.get("text")
                if val:
                    think_parts.append(str(val))
            elif btype in ("text", ""):
                if block.get("text") is not None:
                    text_parts.append(str(block["text"]))
    return "".join(text_parts), "".join(think_parts)


def _message_role(msg: Any) -> str:
    """Normalise ``Message.type`` to ``ai`` / ``tool`` / ``human`` / ...

    LangChain uses different spellings for a message and its streaming chunk:
    ``AIMessage.type == "ai"`` but ``AIMessageChunk.type == "AIMessageChunk"``;
    ``ToolMessage.type == "tool"`` but ``ToolMessageChunk.type ==
    "ToolMessageChunk"``.
    """
    value = getattr(msg, "type", "")
    if not isinstance(value, str):
        return ""
    value = value.lower()
    if value.endswith("chunk"):
        value = value[: -len("chunk")]
    if value.endswith("message"):
        value = value[: -len("message")]
    return value


class DeltaStreamer:
    """Convert ``astream(stream_mode="messages")`` items into display deltas.

    Unlike :func:`message_to_lines`, which renders a *complete* message, this
    yields the small incremental pieces emitted while the model is generating,
    so the UI can render thinking and the answer as they arrive. Feed each
    stream item to :meth:`feed` and render the returned ``(kind, text)`` pairs:

    * ``"thinking"``  -- a fragment of reasoning text (no prefix)
    * ``"assistant"`` -- a fragment of the user-facing answer (no prefix)
    * ``"action"``    -- a complete one-line tool notice (already prefixed)

    The streamer is stateful: it de-duplicates tool notices and tool results,
    which some providers repeat across chunks.
    """

    def __init__(self) -> None:
        self._announced_tool_calls: set[tuple[str, int]] = set()
        self._seen_tool_results: set[str] = set()
        self.text = ""
        self.thinking = ""

    def feed(self, item: Any) -> list[tuple[str, str]]:
        chunk = _stream_message(item)
        if chunk is None:
            return []

        mtype = _message_role(chunk)
        out: list[tuple[str, str]] = []

        # Tool results arrive as complete messages, not deltas.
        if mtype == "tool":
            key = str(
                getattr(chunk, "tool_call_id", None)
                or getattr(chunk, "id", None)
                or id(chunk)
            )
            if key in self._seen_tool_results:
                return []
            self._seen_tool_results.add(key)
            body = message_content(chunk)
            if body and body.strip():
                label = getattr(chunk, "name", None) or "tool"
                out.append(("action", f"\U0001F4E4 {label}: {_short(body)}"))
            return out

        # Skip human/system prompts echoed by the graph.
        if mtype != "ai":
            return []

        # 1. Tool calls: announce each call once, as soon as its name is known.
        for tcc in getattr(chunk, "tool_call_chunks", None) or []:
            if isinstance(tcc, dict):
                name, index = tcc.get("name"), tcc.get("index", 0)
            else:
                name, index = getattr(tcc, "name", None), getattr(tcc, "index", 0)
            if not name:
                continue
            key = (str(getattr(chunk, "id", "") or ""), int(index or 0))
            if key in self._announced_tool_calls:
                continue
            self._announced_tool_calls.add(key)
            out.append(("action", f"\U0001F527 {name}"))

        # 2. Reasoning deltas (from additional_kwargs or content blocks).
        reasoning = message_reasoning(chunk)
        text, block_reasoning = _split_content_blocks(getattr(chunk, "content", ""))
        reasoning = reasoning or block_reasoning

        # 3. Emit both fragments; providers send them in separate chunks so at
        #    most one of the two is non-empty.
        if reasoning:
            self.thinking += reasoning
            out.append(("thinking", reasoning))
        if text:
            self.text += text
            out.append(("assistant", text))
        return out


__all__ += ["DeltaStreamer"]
