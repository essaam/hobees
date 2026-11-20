"""Resolve global ``LLMProvider`` rows into LangChain chat models.

Imported lazily inside execution handlers rather than at CLI startup.
"""

from __future__ import annotations

import os
from typing import Sequence

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel

from hobees.db.models import LLMProvider


# Thinking level type
ThinkingLevel = str  # "off" | "low" | "medium" | "high"


def _apply_thinking_level(
    model: BaseChatModel,
    provider_type: str,
    thinking_level: ThinkingLevel,
) -> BaseChatModel:
    """Apply thinking/reasoning level to a chat model based on provider type.

    ``"off"`` must be handled per provider rather than with a blanket early
    return: some servers think by default and only stop when told to.
    """
    if provider_type == "openai":
        # OpenAI only reasons when asked to, so "off" means sending nothing.
        if thinking_level == "off":
            return model
        model_kwargs = getattr(model, "model_kwargs", {}) or {}
        model_kwargs["reasoning_effort"] = thinking_level
        model.model_kwargs = model_kwargs
        return model

    if provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic
        if isinstance(model, ChatAnthropic):
            if thinking_level == "off":
                # Extended thinking is opt-in, so leave the default (disabled).
                return model
            budget_map = {
                "low": 1024,
                "medium": 4096,
                "high": 16384,
            }
            model.thinking = {
                "type": "enabled",
                "budget_tokens": budget_map.get(thinking_level, 4096),
            }
        return model

    if provider_type == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI
        if isinstance(model, ChatGoogleGenerativeAI):
            if thinking_level == "off":
                # Gemini 2.5 models think by default; a zero budget disables it.
                model.thinking_budget = 0
                return model
            budget_map = {
                "low": 1024,
                "medium": 8192,
                "high": 24576,
            }
            model.thinking_budget = budget_map.get(thinking_level, 8192)
        return model

    if provider_type == "openai_compatible":
        # For openai_compatible (llama.cpp, vLLM, Ollama, OpenRouter, etc.)
        # Use extra_body with reasoning_effort and chat_template_kwargs
        # Note: llama.cpp only supports xhigh, medium, low for reasoning_effort
        # "auto" means don't set reasoning_effort (let model default)
        model_kwargs = getattr(model, "model_kwargs", {}) or {}
        extra_body = model_kwargs.get("extra_body", {}) or {}
        if thinking_level == "off":
            # Qwen3-family templates think by default when the flag is absent,
            # so "off" has to be sent explicitly (this used to be unreachable).
            extra_body["reasoning_effort"] = "none"
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        elif thinking_level == "auto":
            # Don't set reasoning_effort - let the model use its default
            extra_body["chat_template_kwargs"] = {"enable_thinking": True}
        else:
            # Map our levels to llama.cpp supported values
            level_map = {
                "low": "low",
                "medium": "medium",
                "high": "xhigh",  # llama.cpp uses xhigh for high
            }
            extra_body["reasoning_effort"] = level_map.get(thinking_level, "medium")
            extra_body["chat_template_kwargs"] = {"enable_thinking": True}
        model_kwargs["extra_body"] = extra_body
        model.model_kwargs = model_kwargs
        return model

    return model


def get_chat_model(
    provider: LLMProvider,
    model_name: str,
    temperature: float = 0.0,
    callbacks: Sequence[BaseCallbackHandler] | None = None,
    thinking_level: ThinkingLevel = "off",
) -> BaseChatModel:
    """Instantiate the LangChain chat model for a registered provider.

    * ``openai``          -> ``ChatOpenAI``
    * ``anthropic``       -> ``ChatAnthropic``
    * ``google_genai``    -> ``ChatGoogleGenerativeAI``
    * ``openai_compatible`` -> ``ChatOpenAI`` with ``base_url`` (Ollama,
      vLLM, LM Studio, OpenRouter, Groq, Together, DeepSeek, ...)

    The API key is read at runtime from the environment variable named in
    ``provider.api_key_env`` — plaintext secrets are never stored in Postgres.
    Use ``api_key_env=NONE`` for local endpoints that do not require a key.
    """
    callback_list = list(callbacks or [])

    # Ensure OpenAI-compatible reasoning (thinking) fields are preserved so the
    # shell / TUI can display a model's thinking. Idempotent.
    from hobees.core.reasoning_patch import apply_reasoning_capture

    apply_reasoning_capture()

    common = dict(model=model_name, temperature=temperature, callbacks=callback_list)

    ptype = provider.provider_type
    alias = provider.alias

    if ptype == "openai":
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            **common,
            api_key=os.environ.get(provider.api_key_env) if provider.api_key_env != "NONE" else None,
            # Required so token usage is reported on streamed responses;
            # without it telemetry records 0 tokens whenever we stream.
            stream_usage=True,
        )
        return _apply_thinking_level(model, ptype, thinking_level)

    if ptype == "anthropic":
        from langchain_anthropic import ChatAnthropic

        model = ChatAnthropic(
            **common,
            api_key=os.environ.get(provider.api_key_env) if provider.api_key_env != "NONE" else None,
        )
        return _apply_thinking_level(model, ptype, thinking_level)

    if ptype == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(
            **common,
            google_api_key=os.environ.get(provider.api_key_env) if provider.api_key_env != "NONE" else None,
        )
        return _apply_thinking_level(model, ptype, thinking_level)

    if ptype == "openai_compatible":
        from langchain_openai import ChatOpenAI

        # For local endpoints (llama.cpp, vLLM, Ollama, LM Studio) that don't require
        # authentication, we still need to pass a dummy API key to the OpenAI client.
        # The actual API key is read from the environment variable if set, otherwise
        # we use a dummy value.
        if provider.api_key_env != "NONE":
            api_key = os.environ.get(provider.api_key_env)
            # If the env var is set but empty/not set, use dummy key for local endpoints
            if not api_key:
                api_key = "not-needed"
        else:
            # Dummy API key for local endpoints that don't require authentication
            api_key = "not-needed"

        model = ChatOpenAI(
            **common,
            base_url=provider.base_url,
            api_key=api_key,
            # Local servers only include usage in a stream when asked to.
            stream_usage=True,
        )
        return _apply_thinking_level(model, ptype, thinking_level)

    raise ValueError(
        f"Unsupported provider_type {ptype!r} for provider alias {alias!r}"
    )


def resolve_api_key(provider: LLMProvider) -> str | None:
    """Return the runtime API key for a provider, or None when not required."""
    if provider.api_key_env == "NONE":
        return None
    return os.environ.get(provider.api_key_env)


__all__ = ["get_chat_model", "resolve_api_key", "ThinkingLevel"]