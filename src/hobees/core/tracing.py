"""Systematic Hive Activity Tracing and Event Streaming (Phase 3 & 4).

Provides:
- Standardized ``HiveTraceEvent`` model
- ``EventBroker`` pub/sub event bus for live streaming (SSE, WebSockets, CLI)
- ``HiveTraceCallbackHandler`` appending to `.jsonl` audit trails and publishing live events
- ``write_run_manifest`` utility for per-run artifact manifests
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|passwd|secret|credential)",
    re.IGNORECASE,
)
_PRIVATE_REASONING_FIELDS = {
    "thought",
    "reasoning",
    "reasoning_content",
    "thinking",
    "thinking_content",
}
_AUTHORIZATION_HEADER = re.compile(
    r"(?i)(\bAuthorization\s*[:=]\s*)(?:Bearer\s+)?[^\s,;]+(?:\s+[^\s,;]+)?"
)
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)(["']?[a-z0-9_-]*(?:api[_-]?key|token|password|passwd|secret|credential)["']?\s*[:=]\s*)["']?[^\s,;}]+["']?"""
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_KNOWN_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b"
)
_REDACTED = "[REDACTED]"
_SUMMARY_LIMIT = 250


class HiveTraceEvent(BaseModel):
    """Standardized event emitted during Hive operations."""

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    thread_id: str
    hive_name: str
    run_id: int | None = None
    event_type: Literal[
        "HIVE_START",
        "DELEGATE",
        "TOOL_START",
        "TOOL_END",
        "WORKER_START",
        "WORKER_END",
        "BEE_REPLY",
        "SUPERVISOR_SYNTHESIS",
        "HIVE_COMPLETE",
        "HIVE_ERROR",
    ]
    source: str
    target: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventBroker:
    """In-memory pub/sub broker for real-time trace events."""

    _instance: EventBroker | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._subscribers_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> EventBroker:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = EventBroker()
        return cls._instance

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        with self._subscribers_lock:
            self._subscribers[q] = loop
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._subscribers_lock:
            self._subscribers.pop(q, None)

    def publish(self, event: HiveTraceEvent | dict[str, Any]) -> None:
        data = event.model_dump() if isinstance(event, HiveTraceEvent) else event
        with self._subscribers_lock:
            subscribers = list(self._subscribers.items())
        for q, loop in subscribers:
            try:
                loop.call_soon_threadsafe(q.put_nowait, data)
            except RuntimeError:
                logger.warning("Skipping trace event for a closed subscriber loop")


def emit_trace_event(
    event: HiveTraceEvent,
    traces_dir: Path | str | None = None,
) -> None:
    """Persist an event when configured and publish it to live subscribers."""
    event = event.model_copy(
        update={"payload": _sanitize_trace_value(event.payload)}
    )
    if traces_dir is not None:
        trace_file = Path(traces_dir) / f"{event.thread_id}.jsonl"
        try:
            trace_file.parent.mkdir(parents=True, exist_ok=True)
            with trace_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.model_dump()) + "\n")
        except OSError:
            logger.exception("Could not append hive trace file %s", trace_file)
            raise
    EventBroker.get_instance().publish(event)


def _redact_trace_text(value: str) -> str:
    value = _AUTHORIZATION_HEADER.sub(
        lambda match: f"{match.group(1)}{_REDACTED}", value
    )
    value = _BEARER_TOKEN.sub(f"Bearer {_REDACTED}", value)
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{_REDACTED}", value)
    return _KNOWN_TOKEN.sub(_REDACTED, value)


def _sanitize_trace_value(value: Any, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return _REDACTED
    if value is None or isinstance(value, (str, int, float, bool)):
        return _redact_trace_text(value) if isinstance(value, str) else value
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_trace_value(item, str(item_key))
            for item_key, item in value.items()
            if str(item_key).casefold() not in _PRIVATE_REASONING_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_trace_value(item) for item in value]
    return _redact_trace_text(str(value))


def _content_fields(key: str, value: str) -> dict[str, str]:
    from hobees.config import settings

    mode = settings.trace_content_mode
    if mode == "metadata":
        return {}
    content = _redact_trace_text(value)
    if mode == "summary" and len(content) > _SUMMARY_LIMIT:
        content = content[:_SUMMARY_LIMIT] + "..."
    return {key: content}


class HiveTraceCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler recording structured trace events."""

    def __init__(
        self,
        *,
        hive_name: str,
        thread_id: str,
        run_id: int | None = None,
        agent_name: str = "supervisor",
        traces_dir: Path | str | None = None,
    ) -> None:
        self.hive_name = hive_name
        self.thread_id = thread_id
        self.run_id = run_id
        self.agent_name = agent_name
        self.traces_dir = Path(traces_dir) if traces_dir else None
        if self.traces_dir:
            self.traces_dir.mkdir(parents=True, exist_ok=True)
            self.trace_file = self.traces_dir / f"{self.thread_id}.jsonl"
        else:
            self.trace_file = None

        self._tool_starts: dict[str, tuple[float, str]] = {}

    def _emit(self, event: HiveTraceEvent) -> None:
        emit_trace_event(event, self.traces_dir)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "unknown_tool")
        if run_id:
            self._tool_starts[str(run_id)] = (time.monotonic(), tool_name)

        self._emit(
            HiveTraceEvent(
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                run_id=self.run_id,
                event_type="TOOL_START",
                source=self.agent_name,
                target=tool_name,
                payload={
                    "tool_name": tool_name,
                    "argument_names": sorted(str(key) for key in inputs) if inputs else [],
                    "argument_count": len(inputs) if inputs else 0,
                },
            )
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        duration_ms = 0
        out_str = str(output)
        tool_name = None
        if run_id and str(run_id) in self._tool_starts:
            started_at, tool_name = self._tool_starts.pop(str(run_id))
            duration_ms = int((time.monotonic() - started_at) * 1000)

        self._emit(
            HiveTraceEvent(
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                run_id=self.run_id,
                event_type="TOOL_END",
                source=self.agent_name,
                target=tool_name,
                payload={
                    "duration_ms": duration_ms,
                    "output_length": len(out_str),
                    "failed": False,
                },
            )
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        duration_ms = 0
        tool_name = None
        if run_id and str(run_id) in self._tool_starts:
            started_at, tool_name = self._tool_starts.pop(str(run_id))
            duration_ms = int((time.monotonic() - started_at) * 1000)
        self._emit(
            HiveTraceEvent(
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                run_id=self.run_id,
                event_type="TOOL_END",
                source=self.agent_name,
                target=tool_name,
                payload={
                    "duration_ms": duration_ms,
                    "error_type": type(error).__name__,
                    "failed": True,
                    **_content_fields("error_preview", str(error)),
                },
            )
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._emit(
            HiveTraceEvent(
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                run_id=self.run_id,
                event_type="HIVE_ERROR",
                source=self.agent_name,
                target="supervisor" if self.agent_name != "supervisor" else "user",
                payload={
                    "error_type": type(error).__name__,
                    **_content_fields("error_preview", str(error)),
                },
            )
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        # Inspect response generations for handoffs / replies
        for gen_list in response.generations or []:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                if not msg:
                    continue

                tool_calls = getattr(msg, "tool_calls", None) or []
                content = str(getattr(msg, "content", "") or "")

                # Check for handoff/delegation tool calls
                for tc in tool_calls:
                    name = tc.get("name", "")
                    if name.startswith("transfer_to_"):
                        target_worker = name.replace("transfer_to_", "")
                        args = tc.get("args") or {}
                        subtask = args.get("description") or str(args)
                        self._emit(
                            HiveTraceEvent(
                                thread_id=self.thread_id,
                                hive_name=self.hive_name,
                                run_id=self.run_id,
                                event_type="DELEGATE",
                                source="supervisor",
                                target=target_worker,
                                payload={
                                    "task_length": len(subtask),
                                    "call_id": tc.get("id"),
                                    **_content_fields("subtask_preview", subtask),
                                },
                            )
                        )

                # If non-supervisor worker, emit BEE_REPLY
                if self.agent_name != "supervisor" and content.strip():
                    self._emit(
                        HiveTraceEvent(
                            thread_id=self.thread_id,
                            hive_name=self.hive_name,
                            run_id=self.run_id,
                            event_type="BEE_REPLY",
                            source=self.agent_name,
                            target="supervisor",
                            payload={
                                "content_length": len(content),
                                **_content_fields("content_preview", content),
                            },
                        )
                    )
                elif self.agent_name == "supervisor" and content.strip() and not tool_calls:
                    self._emit(
                        HiveTraceEvent(
                            thread_id=self.thread_id,
                            hive_name=self.hive_name,
                            run_id=self.run_id,
                            event_type="SUPERVISOR_SYNTHESIS",
                            source="supervisor",
                            target="user",
                            payload={
                                "content_length": len(content),
                                **_content_fields("content_preview", content),
                            },
                        )
                    )


def write_run_manifest(artifacts_dir: Path, manifest_data: dict[str, Any]) -> Path:
    """Write run_manifest.json inside the hive's artifact directory."""
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifacts_dir / "run_manifest.json"

    # Merge with existing manifest if present (keep run history list)
    existing_runs = []
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                existing_runs = prev.get("runs", [])
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring invalid prior run manifest %s", manifest_path)

    # Insert newest run at start
    existing_runs.insert(0, manifest_data)

    data = {
        "hive_name": manifest_data.get("hive_name"),
        "last_run": manifest_data,
        "runs": existing_runs[:50],  # Keep last 50 runs in manifest
    }
    manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest_path


__all__ = [
    "HiveTraceEvent",
    "EventBroker",
    "HiveTraceCallbackHandler",
    "emit_trace_event",
    "write_run_manifest",
]
