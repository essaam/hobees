"""Backport OpenAI-compatible *reasoning* fields that langchain-openai drops.

langchain-openai (1.x) intentionally does **not** extract ``reasoning_content``
/ ``reasoning`` / ``reasoning_details`` from OpenAI-compatible responses
(see the library's own module docstring). Local and third-party servers that
emit a thinking stream through the OpenAI wire format -- llama.cpp, vLLM,
Ollama, LM Studio, OpenRouter, DeepSeek -- therefore produce reasoning that is
silently discarded before it ever reaches a ``AIMessage``. As a result the
interactive shell and TUI could never display a model's *thinking*.

This module idempotently wraps the library's message-conversion helpers so the
reasoning fields are copied onto ``AIMessage.additional_kwargs``. Because
``stream_mode="updates"`` (LangGraph's default) invokes the model non-streaming,
wrapping ``_convert_dict_to_message`` is what makes the *full* reasoning of a
turn appear on the node's output message. ``_convert_delta_to_message_chunk`` is
wrapped too so token-level (``stream_mode="messages"``) streams work as well.

The wrappers are purely additive: they only add keys to ``additional_kwargs``
and leave every other field untouched.
"""

from __future__ import annotations

import functools
from typing import Any, Mapping, Type

from langchain_core.messages import BaseMessage, BaseMessageChunk

__all__ = ["apply_reasoning_capture", "is_reasoning_patch_active"]

# Keys, in priority order, that carry a model's reasoning on the wire / in the
# converted message.
_REASON_KEYS = ("reasoning_content", "reasoning", "reasoning_details")

_applied = False
_orig_convert_dict: Any = None
_orig_convert_delta: Any = None


def _apply_to(message: BaseMessage, raw: Mapping[str, Any]) -> None:
    extra = message.additional_kwargs
    # Some message factories return the kwargs as an empty shared dict; guard.
    if not isinstance(extra, dict):
        return
    for key in _REASON_KEYS:
        val = raw.get(key)
        if val:
            extra.setdefault(key, val)


def apply_reasoning_capture() -> bool:
    """Wrap langchain-openai's converters to preserve reasoning fields.

    Idempotent -- safe to call from every model-creation path. Returns ``True``
    when the patch was (or already is) active, ``False`` when the underlying
    functions could not be located (older/incompatible library).
    """
    global _applied, _orig_convert_dict, _orig_convert_delta
    if _applied:
        return True

    try:
        import langchain_openai.chat_models.base as base
    except Exception:
        return False

    _orig_convert_dict = base._convert_dict_to_message
    _orig_convert_delta = base._convert_delta_to_message_chunk

    @functools.wraps(_orig_convert_dict)
    def _convert_dict_to_message(raw: Mapping[str, Any]) -> BaseMessage:
        message = _orig_convert_dict(dict(raw))
        _apply_to(message, raw)
        return message

    @functools.wraps(_orig_convert_delta)
    def _convert_delta_to_message_chunk(
        raw: Mapping[str, Any], default_class: Type[BaseMessageChunk]
    ) -> BaseMessageChunk:
        message = _orig_convert_delta(dict(raw), default_class)
        _apply_to(message, raw)
        return message

    base._convert_dict_to_message = _convert_dict_to_message
    base._convert_delta_to_message_chunk = _convert_delta_to_message_chunk
    _applied = True
    return True


def is_reasoning_patch_active() -> bool:
    return _applied


def ensure_reasoning_patch() -> None:
    """Convenience wrapper used at model-creation time."""
    apply_reasoning_capture()