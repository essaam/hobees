"""``TelemetryCallbackHandler`` — LangChain callback writing one
``usage_events`` row per LLM step so live metrics are visible across
terminals and the web API in real time (FR-5, FR-6).

Instantiated per Bee/LLM call during execution; never imported at CLI
top level.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from sqlalchemy import text

from hobees.db.session import session_scope

# Provider alias -> (input_cost_per_1m, output_cost_per_1m) in USD.
_RateTable = dict[str, tuple[float, float]]


_TOKEN_KEYS_IN = ("input_tokens", "prompt_tokens")
_TOKEN_KEYS_OUT = ("output_tokens", "completion_tokens")


def _pick(usage: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        val = usage.get(key)
        if val:
            return int(val)
    return 0


def _usage_from_message(message: Any) -> tuple[int, int]:
    """Read ``usage_metadata`` off a returned AIMessage, if present."""
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict):
        return _pick(usage, _TOKEN_KEYS_IN), _pick(usage, _TOKEN_KEYS_OUT)
    return 0, 0


def _extract_tokens(response: LLMResult) -> tuple[int, int]:
    """Best-effort token extraction across chat-model implementations."""
    input_tokens = output_tokens = 0

    # OpenAI-compatible providers report ``prompt_tokens``/``completion_tokens``
    # while Anthropic/Google-style ones report ``input_tokens``/``output_tokens``;
    # accept both rather than silently recording zeros.
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
    if isinstance(token_usage, dict):
        input_tokens = _pick(token_usage, _TOKEN_KEYS_IN)
        output_tokens = _pick(token_usage, _TOKEN_KEYS_OUT)

    # Per-generation metadata, plus the AIMessage's own usage_metadata.
    for gen_list in response.generations or []:
        for gen in gen_list:
            info = getattr(gen, "generation_info", None) or {}
            for key in ("token_usage", "usage_metadata"):
                usage = info.get(key) if isinstance(info, dict) else None
                if isinstance(usage, dict):
                    input_tokens = max(input_tokens, _pick(usage, _TOKEN_KEYS_IN))
                    output_tokens = max(output_tokens, _pick(usage, _TOKEN_KEYS_OUT))
            msg_in, msg_out = _usage_from_message(getattr(gen, "message", None))
            input_tokens = max(input_tokens, msg_in)
            output_tokens = max(output_tokens, msg_out)

    return input_tokens, output_tokens


class TelemetryCallbackHandler(BaseCallbackHandler):
    """Records latency, token usage and estimated cost for every LLM step."""

    def __init__(
        self,
        *,
        bee_name: str,
        provider_alias: str,
        model_name: str,
        thread_id: str,
        run_id: int | None = None,
        rates: _RateTable | None = None,
        tool_calls: list[Any] | None = None,
        container_name: str | None = None,
        checkpoint_id: str | None = None,
    ) -> None:
        self.bee_name = bee_name
        self.provider_alias = provider_alias
        self.model_name = model_name
        self.thread_id = thread_id
        self.run_id = run_id
        self._rates = rates or {}
        self._tool_calls = tool_calls or []
        self.container_name = container_name
        self.checkpoint_id = checkpoint_id
        self._starts: dict[str, float] = {}

    # -- LangChain callback API -------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._starts[str(run_id)] = time.monotonic()

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(str(run_id), None)
        latency_ms = int((time.monotonic() - start) * 1000) if start is not None else 0

        metadata = kwargs.get("metadata") or {}
        db_run_id = metadata.get("hobees_run_id", self.run_id)
        input_tokens, output_tokens = _extract_tokens(response)
        estimated_cost_usd = self._estimate_cost(input_tokens, output_tokens)
        tool_calls = metadata.get("hobees_tool_calls", self._tool_calls)

        self._insert(
            db_run_id=db_run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
            tool_calls=json.dumps(tool_calls) if tool_calls else "[]",
        )

    # -- internals --------------------------------------------------------

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        rates = self._rates.get(self.provider_alias)
        if not rates:
            return 0.0
        input_per_1m, output_per_1m = rates
        return round(
            input_tokens / 1_000_000 * input_per_1m
            + output_tokens / 1_000_000 * output_per_1m,
            6,
        )

    def _insert(
        self,
        *,
        db_run_id: int | None,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
        latency_ms: int,
        tool_calls: list[Any],
    ) -> None:
        with session_scope() as session:
            session.execute(
                text(
                    """
                    INSERT INTO usage_events
                        (run_id, thread_id, bee_name, provider_alias, model_name,
                         container_name, checkpoint_id,
                         input_tokens, output_tokens, estimated_cost_usd,
                         latency_ms, tool_calls)
                    VALUES
                        (:run_id, :thread_id, :bee_name, :provider_alias, :model_name,
                         :container_name, :checkpoint_id,
                         :input_tokens, :output_tokens, :estimated_cost_usd,
                         :latency_ms, :tool_calls)
                    """
                ),
                {
                    "run_id": db_run_id,
                    "thread_id": self.thread_id,
                    "container_name": self.container_name,
                    "checkpoint_id": self.checkpoint_id,
                    "bee_name": self.bee_name,
                    "provider_alias": self.provider_alias,
                    "model_name": self.model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "latency_ms": latency_ms,
                    "tool_calls": tool_calls,
                },
            )


__all__ = ["TelemetryCallbackHandler", "build_telemetry_handler"]


def build_telemetry_handler(
    provider,
    *,
    bee_name: str,
    model_name: str,
    thread_id: str,
    run_id: int | None = None,
    tool_calls: list[Any] | None = None,
) -> TelemetryCallbackHandler:
    """Build a :class:`TelemetryCallbackHandler` wired to a provider's rates.

    ``provider`` is any object exposing ``alias``, ``input_cost_per_1m`` and
    ``output_cost_per_1m`` (an ``LLMProvider`` row). Used by the interactive
    shell and TUI so a single Bee / assistant turn records ``usage_events`` the
    same way a Hive does.
    """
    alias = provider.alias
    rates = {
        alias: (
            float(getattr(provider, "input_cost_per_1m", 0) or 0),
            float(getattr(provider, "output_cost_per_1m", 0) or 0),
        )
    }
    return TelemetryCallbackHandler(
        bee_name=bee_name,
        provider_alias=alias,
        model_name=model_name,
        thread_id=thread_id,
        run_id=run_id,
        rates=rates,
        tool_calls=tool_calls,
    )
