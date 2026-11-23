"""FastAPI Web Application for hobees Visual Trace Explorer & Hive Studio.

Serves:
1. Bundled React SPA static assets from ``src/hobees/web/static/`` (zero Node runtime)
2. REST API under ``/api/v1`` for Workbench, Traces, Studio, Approvals, Memory & Artifacts
3. Server-Sent Events (SSE) for live run streaming and approval updates
4. HITL approval resolution and LangGraph checkpoint time-travel replay
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import desc, func

from hobees.config import settings
from hobees.core.approval import (
    APPROVAL_MODES,
    ApprovalMiddleware,
    resolve_approval_mode,
    resolve_container_name,
    resolve_thread_id,
)
from hobees.core.tracing import (
    EventBroker,
    HiveTraceCallbackHandler,
    HiveTraceEvent,
    emit_trace_event,
    trace_filename,
)
from hobees.db.backends import get_database_backend
from hobees.db.models import (
    ApprovalEvent,
    Bee,
    BeeSkill,
    Hive,
    HiveMembership,
    LLMProvider,
    Memory,
    Run,
    Skill,
    UsageEvent,
)
from hobees.db.session import get_engine, session_scope

logger = logging.getLogger(__name__)

# Guard against broken Windows registry MIME mappings for ES modules / CSS / SVG.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class StatusResponse(BaseModel):
    status: str
    timestamp: datetime
    database: str
    container: str
    read_only: bool
    version: str


class ContainerListResponse(BaseModel):
    containers: list[str]


class ProviderResponse(BaseModel):
    id: int
    alias: str
    provider_type: str
    base_url: Optional[str] = None
    api_key_env: str = "NONE"
    default_model: Optional[str] = None
    assistant_model: Optional[str] = None
    available_models: list[str] = Field(default_factory=list)
    context_window_tokens: int = 128000
    input_cost_per_1m: float = 0.0
    output_cost_per_1m: float = 0.0


class ProviderCreate(BaseModel):
    alias: str
    provider_type: str
    base_url: Optional[str] = None
    api_key_env: str = "NONE"
    default_model: Optional[str] = None
    assistant_model: Optional[str] = None
    input_cost_per_1m: float = 0.0
    output_cost_per_1m: float = 0.0
    context_window_tokens: int = 128000


class ProviderUpdate(BaseModel):
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    default_model: Optional[str] = None
    assistant_model: Optional[str] = None
    input_cost_per_1m: Optional[float] = None
    output_cost_per_1m: Optional[float] = None
    context_window_tokens: Optional[int] = None


class BeeResponse(BaseModel):
    id: int
    name: str
    role_description: str
    system_prompt: str
    provider_id: int
    provider_alias: Optional[str] = None
    model_name: str
    temperature: float = 0.0
    thinking_level: str = "off"
    tool_names: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)


class BeeCreate(BaseModel):
    name: str
    role_description: str
    system_prompt: str = ""
    provider_id: int
    model_name: str
    temperature: float = 0.0
    thinking_level: str = "off"
    tool_names: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)


class BeeUpdate(BaseModel):
    role_description: Optional[str] = None
    system_prompt: Optional[str] = None
    provider_id: Optional[int] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    thinking_level: Optional[str] = None
    tool_names: Optional[list[str]] = None
    require_approval: Optional[list[str]] = None


class HiveResponse(BaseModel):
    id: int
    name: str
    goal_description: Optional[str] = None
    supervisor_provider_id: int
    supervisor_provider_alias: Optional[str] = None
    supervisor_model_name: str
    supervisor_prompt: Optional[str] = None
    supervisor_thinking_level: str = "medium"
    is_dynamic: bool = False
    project_path: Optional[str] = None
    bee_names: list[str] = Field(default_factory=list)
    bee_ids: list[int] = Field(default_factory=list)


class HiveCreate(BaseModel):
    name: str
    goal_description: Optional[str] = None
    supervisor_provider_id: int
    supervisor_model_name: str
    supervisor_prompt: Optional[str] = None
    supervisor_thinking_level: str = "medium"
    is_dynamic: bool = False
    project_path: Optional[str] = None
    bee_ids: list[int] = Field(default_factory=list)


class HiveUpdate(BaseModel):
    goal_description: Optional[str] = None
    supervisor_provider_id: Optional[int] = None
    supervisor_model_name: Optional[str] = None
    supervisor_prompt: Optional[str] = None
    supervisor_thinking_level: Optional[str] = None
    is_dynamic: Optional[bool] = None
    project_path: Optional[str] = None
    bee_ids: Optional[list[int]] = None


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolsResponse(BaseModel):
    tools: list[ToolSchema]


class SkillResponse(BaseModel):
    id: int
    name: str
    description: str
    instructions: str
    tags: list[str] = Field(default_factory=list)
    source_thread_id: Optional[str] = None
    usage_count: int = 0


class ConfigYamlResponse(BaseModel):
    yaml: str


class RunCreate(BaseModel):
    scope: Literal["hive", "bee", "assistant"] = "hive"
    entity_name: str = "default"
    prompt: str
    thread_id: Optional[str] = None
    container_name: Optional[str] = None
    approval_mode: Optional[str] = None
    thinking: Optional[str] = None


class RunResponse(BaseModel):
    thread_id: str
    status: str


class TraceSummaryItem(BaseModel):
    container: str
    thread_id: str
    status: str
    mode: str
    goal: str
    hive_name: Optional[str] = None
    entity_name: str = "default"
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    duration_ms: Optional[int] = None
    pending_approvals: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ApprovalRecord(BaseModel):
    id: int
    container_name: str
    thread_id: str
    checkpoint_id: Optional[str] = None
    hive_name: Optional[str] = None
    bee_name: str
    tool_name: str
    tool_call_id: str
    approval_mode: str
    decision: str
    wait_ms: Optional[int] = None
    original_args: dict[str, Any] = Field(default_factory=dict)
    final_args: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    requested_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class TraceNode(BaseModel):
    id: str
    checkpoint_id: Optional[str] = None
    parent_checkpoint_id: Optional[str] = None
    step_index: int
    node: str
    target: Optional[str] = None
    action_type: str
    status: str = "success"
    timestamp: Optional[str] = None
    payload_summary: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_io: Optional[dict[str, Any]] = None
    approval_info: list[ApprovalRecord] = Field(default_factory=list)
    metrics: Optional[dict[str, Any]] = None
    checkpoint_state: Optional[dict[str, Any]] = None


class TraceDetailResponse(BaseModel):
    container: str
    thread_id: str
    status: str
    mode: str = "hive"
    goal: str = ""
    hive_name: Optional[str] = None
    entity_name: str = "default"
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    total_latency_ms: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    has_checkpoints: bool = False
    nodes: list[TraceNode] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    checkpoint_id: str
    patch_message: Optional[str] = None
    approval_mode: Optional[str] = None


class ReplayResponse(BaseModel):
    thread_id: str
    forked_from: str
    status: str


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalRecord]


class ApprovalResolveRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    args: Optional[dict[str, Any]] = None
    reason: Optional[str] = None


class ApprovalResolveResponse(BaseModel):
    success: bool
    thread_id: str
    checkpoint_id: str
    resumed: bool = False
    status: str = "resolved"


class MemoryItem(BaseModel):
    id: int
    namespace: str
    key: str
    content: str
    source_thread_id: Optional[str] = None
    updated_at: Optional[datetime] = None


class MemoryListResponse(BaseModel):
    memories: list[MemoryItem]
    namespaces: list[str] = Field(default_factory=list)


class MemoryCreate(BaseModel):
    namespace: str
    key: str
    content: str


class ArtifactItem(BaseModel):
    path: str
    name: str
    hive: Optional[str] = None
    size: int
    modified: datetime


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactItem]
    hives: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("hobees")
    except Exception:
        return "0.1.0"


def _parse_json_obj(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"value": data}
    except (TypeError, json.JSONDecodeError):
        return {"raw": str(raw)}


def _serialize_approval(event: ApprovalEvent) -> ApprovalRecord:
    wait_ms = None
    if event.resolved_at and event.requested_at:
        req = event.requested_at
        res = event.resolved_at
        if req.tzinfo is None:
            req = req.replace(tzinfo=timezone.utc)
        if res.tzinfo is None:
            res = res.replace(tzinfo=timezone.utc)
        wait_ms = max(0, int((res - req).total_seconds() * 1000))

    return ApprovalRecord(
        id=event.id,
        container_name=event.container_name,
        thread_id=event.thread_id,
        checkpoint_id=event.checkpoint_id,
        hive_name=event.hive_name,
        bee_name=event.bee_name,
        tool_name=event.tool_name,
        tool_call_id=event.tool_call_id,
        approval_mode=event.approval_mode,
        decision=event.decision,
        wait_ms=wait_ms,
        original_args=_parse_json_obj(event.original_args_json),
        final_args=_parse_json_obj(event.final_args_json) if event.final_args_json else None,
        reason=event.reason,
        requested_at=event.requested_at,
        resolved_at=event.resolved_at,
    )


def _entity_from_thread(thread_id: str, hive_name: str | None) -> str:
    if hive_name:
        return hive_name
    parts = thread_id.split(":", 3)
    if len(parts) == 4:
        return parts[2]
    return "default"


def _scope_from_thread(thread_id: str, mode: str | None = None) -> str:
    parts = thread_id.split(":", 3)
    if len(parts) == 4 and parts[1] in {"hive", "bee", "assistant"}:
        return parts[1]
    if mode in {"bee", "assistant"}:
        return mode
    return "hive"


def _serialize_provider(p: LLMProvider) -> ProviderResponse:
    return ProviderResponse(
        id=p.id,
        alias=p.alias,
        provider_type=p.provider_type,
        base_url=p.base_url,
        api_key_env=p.api_key_env or "NONE",
        default_model=p.default_model,
        assistant_model=getattr(p, "assistant_model", None),
        available_models=list(p.available_models or []),
        context_window_tokens=p.context_window_tokens or 128000,
        input_cost_per_1m=float(p.input_cost_per_1m or 0.0),
        output_cost_per_1m=float(p.output_cost_per_1m or 0.0),
    )


def _serialize_bee(b: Bee) -> BeeResponse:
    return BeeResponse(
        id=b.id,
        name=b.name,
        role_description=b.role_description,
        system_prompt=b.system_prompt or "",
        provider_id=b.provider_id,
        provider_alias=b.provider.alias if b.provider else None,
        model_name=b.model_name,
        temperature=float(b.temperature or 0.0),
        thinking_level=b.thinking_level or "off",
        tool_names=list(b.tool_names or []),
        require_approval=list(b.require_approval or []),
    )


def _serialize_hive(h: Hive) -> HiveResponse:
    members = [m.bee for m in (h.memberships or []) if m.bee]
    return HiveResponse(
        id=h.id,
        name=h.name,
        goal_description=h.goal_description,
        supervisor_provider_id=h.supervisor_provider_id,
        supervisor_provider_alias=h.supervisor_provider.alias if h.supervisor_provider else None,
        supervisor_model_name=h.supervisor_model_name,
        supervisor_prompt=h.supervisor_prompt,
        supervisor_thinking_level=h.supervisor_thinking_level or "medium",
        is_dynamic=bool(h.is_dynamic),
        project_path=h.project_path,
        bee_names=[b.name for b in members],
        bee_ids=[b.id for b in members],
    )


def _load_trace_events(thread_id: str, extra_roots: list[Path] | None = None) -> list[dict[str, Any]]:
    """Load JSONL trace events for a thread from configured artifact locations."""
    events: list[dict[str, Any]] = []
    seen_lines: set[str] = set()
    candidates = [trace_filename(thread_id), f"{thread_id}.jsonl"]
    roots: list[Path] = []
    if extra_roots:
        roots.extend(extra_roots)
    roots.extend([
        settings.artifacts_root,
        Path.cwd() / "artifacts",
        Path.home() / ".hobees" / "artifacts",
    ])

    visited_files: set[Path] = set()
    for root in roots:
        if not root or not root.exists():
            continue
        for fname in candidates:
            # Avoid invalid glob patterns on Windows when thread_id contains ':'
            if ":" in fname:
                continue
            try:
                for trace_file in root.rglob(fname):
                    resolved = trace_file.resolve()
                    if resolved in visited_files or not resolved.is_file():
                        continue
                    visited_files.add(resolved)
                    for line in resolved.read_text(encoding="utf-8").splitlines():
                        stripped = line.strip()
                        if not stripped or stripped in seen_lines:
                            continue
                        seen_lines.add(stripped)
                        try:
                            data = json.loads(stripped)
                            if data.get("thread_id") == thread_id:
                                events.append(data)
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue

    events.sort(key=lambda ev: str(ev.get("timestamp") or ""))
    return events


def _safe_jsonable(value: Any, depth: int = 0) -> Any:
    """Recursively convert LangGraph state snapshots into JSON-safe structures."""
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_jsonable(v, depth + 1) for v in value]
    # LangChain message-like objects
    if hasattr(value, "type") and hasattr(value, "content"):
        msg: dict[str, Any] = {
            "type": str(getattr(value, "type", type(value).__name__)),
            "name": getattr(value, "name", None),
            "content": _safe_jsonable(getattr(value, "content", ""), depth + 1),
        }
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            msg["tool_calls"] = _safe_jsonable(tool_calls, depth + 1)
        tool_call_id = getattr(value, "tool_call_id", None)
        if tool_call_id:
            msg["tool_call_id"] = str(tool_call_id)
        return msg
    if hasattr(value, "model_dump"):
        try:
            return _safe_jsonable(value.model_dump(), depth + 1)
        except Exception:
            return str(value)
    return str(value)


def _extract_messages_from_snapshot(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, dict):
        return []
    raw_msgs = values.get("messages")
    if not isinstance(raw_msgs, list):
        return []
    return [_safe_jsonable(m) for m in raw_msgs]


async def _load_checkpoint_snapshots(
    thread_id: str,
    hive_id: int | None,
) -> list[dict[str, Any]]:
    """Fetch chronological LangGraph checkpoint snapshots for a thread if available."""
    from hobees.cli.shell import _get_async_checkpointer

    engine = get_engine()
    try:
        saver, stack = await _get_async_checkpointer(engine.url)
    except Exception:
        return []

    snapshots: list[dict[str, Any]] = []
    try:
        config = {"configurable": {"thread_id": thread_id}}
        async for cp_tuple in saver.alist(config):
            cp = getattr(cp_tuple, "checkpoint", {}) or {}
            cp_cfg = getattr(cp_tuple, "config", {}) or {}
            parent_cfg = getattr(cp_tuple, "parent_config", None) or {}
            metadata = getattr(cp_tuple, "metadata", {}) or {}
            cp_id = (cp_cfg.get("configurable") or {}).get("checkpoint_id") or cp.get("id")
            parent_id = (parent_cfg.get("configurable") or {}).get("checkpoint_id")
            channel_values = cp.get("channel_values") or {}
            pending_writes = getattr(cp_tuple, "pending_writes", None) or []
            snapshots.append({
                "checkpoint_id": str(cp_id) if cp_id else None,
                "parent_checkpoint_id": str(parent_id) if parent_id else None,
                "ts": cp.get("ts"),
                "metadata": _safe_jsonable(metadata),
                "values": _safe_jsonable(channel_values),
                "pending_writes": _safe_jsonable(pending_writes),
            })
    except Exception as exc:
        logger.debug("Could not read checkpoints for %s: %s", thread_id, exc)
    finally:
        await stack.aclose()

    # Checkpointer returns newest first; reverse for chronological order.
    snapshots.reverse()
    return snapshots


def _build_unified_trace_nodes(
    trace_events: list[dict[str, Any]],
    approvals: list[ApprovalRecord],
    usage_rows: list[UsageEvent],
    checkpoints: list[dict[str, Any]],
) -> list[TraceNode]:
    """Build an ordered execution tree combining JSONL events, checkpoints, approvals, and usage."""
    nodes: list[TraceNode] = []

    approvals_by_cp: dict[str, list[ApprovalRecord]] = {}
    approvals_by_tool: dict[tuple[str, str], list[ApprovalRecord]] = {}
    attached_approval_ids: set[int] = set()
    for a in approvals:
        if a.checkpoint_id:
            approvals_by_cp.setdefault(a.checkpoint_id, []).append(a)
        approvals_by_tool.setdefault((a.bee_name, a.tool_name), []).append(a)

    usage_by_bee: dict[str, list[UsageEvent]] = {}
    for u in usage_rows:
        usage_by_bee.setdefault(u.bee_name, []).append(u)
    usage_cursor: dict[str, int] = {}

    def pop_usage(actor: str) -> dict[str, Any] | None:
        # Match either exact bee_name or "<hive>_supervisor" for supervisor
        candidates = [actor]
        if actor == "supervisor":
            candidates.extend(k for k in usage_by_bee if k.endswith("_supervisor"))
        for key in candidates:
            items = usage_by_bee.get(key) or []
            idx = usage_cursor.get(key, 0)
            if idx < len(items):
                u = items[idx]
                usage_cursor[key] = idx + 1
                return {
                    "input_tokens": u.input_tokens or 0,
                    "output_tokens": u.output_tokens or 0,
                    "total_tokens": (u.input_tokens or 0) + (u.output_tokens or 0),
                    "latency_ms": u.latency_ms or 0,
                    "model": u.model_name,
                    "provider": u.provider_alias,
                    "estimated_cost_usd": float(u.estimated_cost_usd or 0.0),
                }
        return None

    # Pair TOOL_START -> TOOL_END durations & errors
    tool_end_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ev in trace_events:
        if ev.get("event_type") == "TOOL_END":
            key = (str(ev.get("source") or ""), str(ev.get("target") or ""))
            tool_end_by_key.setdefault(key, []).append(ev)

    # Map checkpoints onto nodes so time-travel replay has valid checkpoint IDs
    cp_index = 0
    step_idx = 0

    for ev in trace_events:
        etype = str(ev.get("event_type") or "")
        source = str(ev.get("source") or "system")
        target = ev.get("target")
        payload = ev.get("payload") or {}
        ts = ev.get("timestamp")

        if etype in {"HIVE_START", "WORKER_START", "WORKER_END", "TOOL_END"}:
            # Skip redundant lifecycle noise when richer events carry the step;
            # keep HIVE_START only if there are no other events.
            continue

        cp = checkpoints[cp_index] if cp_index < len(checkpoints) else None
        cp_id = payload.get("checkpoint_id") or (cp["checkpoint_id"] if cp else None)
        parent_cp_id = cp["parent_checkpoint_id"] if cp else None
        if cp is not None:
            cp_index += 1

        action_type = "step"
        status = "success"
        summary = etype
        messages: list[dict[str, Any]] = []
        tool_io: dict[str, Any] | None = None
        node_approvals: list[ApprovalRecord] = []
        metrics: dict[str, Any] | None = None

        if etype == "DELEGATE":
            action_type = "delegation"
            preview = payload.get("subtask_preview") or ""
            summary = f'Delegated to "{target}"' + (f" — {preview[:90]}" if preview else "")
            if preview:
                messages.append({"role": "supervisor", "label": f"Handoff → {target}", "content": preview})
            metrics = pop_usage("supervisor")
        elif etype == "TOOL_START":
            action_type = "tool_call"
            tool_name = str(payload.get("tool_name") or target or "tool")
            summary = f"Tool: {tool_name}"
            end_list = tool_end_by_key.get((source, tool_name)) or []
            end_ev = end_list.pop(0) if end_list else None
            end_payload = (end_ev or {}).get("payload") or {}
            failed = bool(end_payload.get("failed"))
            if failed:
                status = "failed"
            tool_io = {
                "tool_name": tool_name,
                "argument_names": payload.get("argument_names") or [],
                "argument_count": payload.get("argument_count") or 0,
                "duration_ms": end_payload.get("duration_ms"),
                "output_length": end_payload.get("output_length"),
                "failed": failed,
                "error_type": end_payload.get("error_type"),
                "error_preview": end_payload.get("error_preview"),
            }
            # Attach matching approvals for this bee + tool
            for a in approvals_by_tool.get((source, tool_name), []):
                if a.id not in attached_approval_ids:
                    node_approvals.append(a)
                    attached_approval_ids.add(a.id)
                    if a.decision == "pending":
                        status = "awaiting_approval"
                    elif a.decision == "reject":
                        status = "rejected"
                    elif a.decision == "edit":
                        status = "edited"
                    break
        elif etype == "BEE_REPLY":
            action_type = "llm_response"
            preview = payload.get("content_preview") or ""
            summary = preview[:110] if preview else f"{source} replied"
            if preview:
                messages.append({"role": source, "label": f"{source} → supervisor", "content": preview})
            metrics = pop_usage(source)
        elif etype == "SUPERVISOR_SYNTHESIS":
            action_type = "final_output"
            preview = payload.get("content_preview") or ""
            summary = preview[:110] if preview else "Final Response"
            if preview:
                messages.append({"role": "supervisor", "label": "Final Synthesis", "content": preview})
            metrics = pop_usage("supervisor")
        elif etype == "HIVE_COMPLETE":
            action_type = "final_output"
            summary = "Run completed"
        elif etype == "HIVE_ERROR":
            action_type = "error"
            status = "failed"
            err = payload.get("error") or payload.get("error_preview") or payload.get("error_type") or "Execution error"
            summary = f"Error: {str(err)[:110]}"
            messages.append({"role": "error", "label": "Error", "content": str(err)})
        elif etype == "APPROVAL_REQUIRED":
            action_type = "approval_gate"
            status = "awaiting_approval"
            summary = f"Awaiting approval: {payload.get('tool') or target or 'tool'}"

        if cp_id and cp_id in approvals_by_cp:
            for a in approvals_by_cp[cp_id]:
                if a.id not in attached_approval_ids:
                    node_approvals.append(a)
                    attached_approval_ids.add(a.id)

        nodes.append(TraceNode(
            id=f"step_{step_idx}",
            checkpoint_id=cp_id,
            parent_checkpoint_id=parent_cp_id,
            step_index=step_idx,
            node=source,
            target=str(target) if target else None,
            action_type=action_type,
            status=status,
            timestamp=str(ts) if ts else None,
            payload_summary=summary,
            messages=messages,
            tool_io=tool_io,
            approval_info=node_approvals,
            metrics=metrics,
            checkpoint_state=cp,
        ))
        step_idx += 1

    # If no JSONL events were present, build nodes directly from LangGraph checkpoints.
    if not nodes and checkpoints:
        for cp in checkpoints:
            cp_id = cp.get("checkpoint_id")
            msgs = _extract_messages_from_snapshot(cp.get("values"))
            last_msg = msgs[-1] if msgs else None
            meta = cp.get("metadata") or {}
            source = str(meta.get("source") or (last_msg or {}).get("name") or "graph")
            msg_type = (last_msg or {}).get("type", "")
            content_str = str((last_msg or {}).get("content") or "")
            action_type = "llm_response"
            summary = content_str[:110] if content_str else f"Checkpoint {str(cp_id or '')[:8]}"
            if msg_type == "human":
                action_type = "input"
                summary = f"Prompt: {content_str[:100]}"
            elif (last_msg or {}).get("tool_calls"):
                action_type = "tool_call"
                tc = last_msg["tool_calls"][0]
                summary = f"Tool: {tc.get('name', 'tool')}"
            elif msg_type == "tool":
                action_type = "tool_result"
                summary = f"Tool output: {content_str[:90]}"

            cp_approvals = []
            if cp_id and cp_id in approvals_by_cp:
                for a in approvals_by_cp[cp_id]:
                    cp_approvals.append(a)
                    attached_approval_ids.add(a.id)

            status = "success"
            if any(a.decision == "pending" for a in cp_approvals):
                status = "awaiting_approval"
            elif any(a.decision == "reject" for a in cp_approvals):
                status = "rejected"

            nodes.append(TraceNode(
                id=f"cp_{step_idx}",
                checkpoint_id=cp_id,
                parent_checkpoint_id=cp.get("parent_checkpoint_id"),
                step_index=step_idx,
                node=source,
                action_type=action_type,
                status=status,
                timestamp=str(cp.get("ts")) if cp.get("ts") else None,
                payload_summary=summary,
                messages=[{"role": m.get("type", "message"), "label": m.get("name") or m.get("type", "message"), "content": str(m.get("content") or "")} for m in msgs[-3:]],
                approval_info=cp_approvals,
                checkpoint_state=cp,
            ))
            step_idx += 1

    # Ensure any remaining unattached approval gates (e.g. paused container runs without JSONL) are visible as nodes.
    for a in approvals:
        if a.id in attached_approval_ids:
            continue
        status = (
            "awaiting_approval" if a.decision == "pending"
            else "rejected" if a.decision == "reject"
            else "edited" if a.decision == "edit"
            else "success"
        )
        nodes.append(TraceNode(
            id=f"gate_{a.id}",
            checkpoint_id=a.checkpoint_id,
            step_index=step_idx,
            node=a.bee_name,
            target=a.tool_name,
            action_type="approval_gate",
            status=status,
            timestamp=a.requested_at.isoformat() if a.requested_at else None,
            payload_summary=f"Gate ({a.approval_mode}): {a.tool_name} [{a.decision}]",
            tool_io={
                "tool_name": a.tool_name,
                "tool_call_id": a.tool_call_id,
                "original_args": a.original_args,
                "final_args": a.final_args,
            },
            approval_info=[a],
        ))
        step_idx += 1

    # Attach latest checkpoint to last node if checkpoints exist and last node lacks one
    if checkpoints and nodes and not any(n.checkpoint_id for n in nodes):
        latest_cp = checkpoints[-1]
        nodes[-1].checkpoint_id = latest_cp.get("checkpoint_id")
        nodes[-1].checkpoint_state = latest_cp

    return nodes


async def _run_hive_graph_task(
    *,
    hive_id: int,
    thread_id: str,
    run_id: int,
    prompt: str | None,
    approval_mode: str | None,
    thinking: str | None,
    container_name: str,
    resume_payload: dict[str, Any] | None = None,
    replay_checkpoint_id: str | None = None,
    patch_message: str | None = None,
) -> None:
    """Execute, resume, or replay a Hive graph in the background."""
    from langgraph.types import Command
    from hobees.core.hive_builder import hive_app_async

    with session_scope() as session:
        hive = session.get(Hive, hive_id)
        if not hive:
            return
        bees = [m.bee for m in hive.memberships if m.bee]
        provider_ids = {b.provider_id for b in bees} | {hive.supervisor_provider_id}
        providers = {
            p.id: p
            for p in session.query(LLMProvider).filter(LLMProvider.id.in_(provider_ids)).all()
        }
        # Detach-safe attribute access: eager fields already loaded (expire_on_commit=False)

    art_path = Path(hive.project_path) if hive.project_path else settings.artifacts_root / hive.name
    art_path.mkdir(parents=True, exist_ok=True)
    traces_dir = art_path / "traces"

    effective_mode = resolve_approval_mode(
        approval_mode if approval_mode in APPROVAL_MODES else None,
        interactive=False,
    )

    try:
        async with hive_app_async(
            hive,
            bees,
            providers,
            str(get_engine().url),
            thread_id,
            run_id,
            thinking,
            artifact_root=art_path,
            approval_mode=effective_mode,
            container_name=container_name,
        ) as graph_app:
            invoke_config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
            invoke_input: Any

            if replay_checkpoint_id:
                replay_cfg: dict[str, Any] = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": replay_checkpoint_id,
                    }
                }
                if patch_message:
                    forked_cfg = await graph_app.aupdate_state(
                        replay_cfg,
                        {"messages": [("user", patch_message)]},
                    )
                    if isinstance(forked_cfg, dict):
                        replay_cfg = forked_cfg
                invoke_input = None
                invoke_config = replay_cfg
            elif resume_payload is not None:
                invoke_input = Command(resume=resume_payload)
            else:
                invoke_input = {"messages": [("user", prompt or "")]}

            result = await graph_app.ainvoke(invoke_input, config=invoke_config)

        interrupts = result.get("__interrupt__", []) if isinstance(result, dict) else []
        awaiting = bool(interrupts)

        if awaiting:
            for item in interrupts:
                payload = getattr(item, "value", None) or (item if isinstance(item, dict) else {})
                if isinstance(payload, dict):
                    emit_trace_event(
                        HiveTraceEvent(
                            thread_id=thread_id,
                            hive_name=hive.name,
                            run_id=run_id,
                            event_type="TOOL_START",
                            source=str(payload.get("bee") or "worker"),
                            target=str(payload.get("tool") or "tool"),
                            payload={
                                "tool_name": payload.get("tool"),
                                "awaiting_approval": True,
                            },
                        ),
                        traces_dir,
                    )

        with session_scope() as session:
            run_obj = session.get(Run, run_id)
            if run_obj:
                run_obj.status = "awaiting_approval" if awaiting else "completed"
                run_obj.completed_at = None if awaiting else datetime.now(timezone.utc)
                run_obj.artifacts_dir = str(art_path.resolve())
    except Exception as exc:
        logger.exception("Web hive run failed for thread %s: %s", thread_id, exc)
        with session_scope() as session:
            run_obj = session.get(Run, run_id)
            if run_obj:
                run_obj.status = "failed"
                run_obj.completed_at = datetime.now(timezone.utc)


async def _run_single_bee_task(
    *,
    bee_id: int,
    thread_id: str,
    run_id: int,
    prompt: str | None,
    approval_mode: str | None,
    thinking: str | None,
    container_name: str,
    resume_payload: dict[str, Any] | None = None,
) -> None:
    """Execute or resume a single Worker Bee or Assistant run in the background."""
    from langchain.agents import create_agent
    from langgraph.types import Command
    from hobees.cli.shell import _get_async_checkpointer
    from hobees.core.llm_factory import get_chat_model
    from hobees.core.memory_manager import build_memory_block, extract_namespaces
    from hobees.core.telemetry import TelemetryCallbackHandler
    from hobees.core.tool_registry import get_tools, set_thread_context

    with session_scope() as session:
        bee = session.get(Bee, bee_id)
        if not bee:
            return
        provider = session.get(LLMProvider, bee.provider_id)
        if not provider:
            return

    art_path = settings.artifacts_root / bee.name
    art_path.mkdir(parents=True, exist_ok=True)
    (art_path / "output").mkdir(parents=True, exist_ok=True)
    traces_dir = art_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    set_thread_context(thread_id, project_root=str(art_path.resolve()))

    effective_mode = resolve_approval_mode(
        approval_mode if approval_mode in APPROVAL_MODES else None,
        interactive=False,
    )
    effective_thinking = thinking if thinking and thinking != "auto" else (bee.thinking_level or "off")

    emit_trace_event(
        HiveTraceEvent(
            thread_id=thread_id,
            hive_name=bee.name,
            run_id=run_id,
            event_type="HIVE_START",
            source="system",
            target=bee.name,
            payload={"project_root": str(art_path.resolve())},
        ),
        traces_dir,
    )

    saver, stack = await _get_async_checkpointer(get_engine().url)
    try:
        trace_handler = HiveTraceCallbackHandler(
            hive_name=bee.name,
            thread_id=thread_id,
            run_id=run_id,
            agent_name=bee.name,
            traces_dir=traces_dir,
        )
        telemetry_handler = TelemetryCallbackHandler(
            bee_name=bee.name,
            provider_alias=provider.alias,
            model_name=bee.model_name,
            thread_id=thread_id,
            container_name=container_name,
            run_id=run_id,
            rates={provider.alias: (float(provider.input_cost_per_1m), float(provider.output_cost_per_1m))},
        )
        model = get_chat_model(
            provider,
            bee.model_name,
            float(bee.temperature or 0.0),
            callbacks=[telemetry_handler, trace_handler],
            thinking_level=effective_thinking,
        )
        mem_block = build_memory_block(extract_namespaces(global_=True, bee_name=bee.name))
        sys_prompt = bee.system_prompt or bee.role_description
        if mem_block:
            sys_prompt = f"{sys_prompt}\n\n{mem_block}"

        agent = create_agent(
            model=model,
            tools=get_tools(bee.tool_names),
            system_prompt=sys_prompt,
            name=bee.name,
            checkpointer=saver,
            middleware=[
                ApprovalMiddleware(
                    bee_name=bee.name,
                    hive_name=bee.name,
                    thread_id=thread_id,
                    container_name=container_name,
                    approval_mode=effective_mode,
                    require_approval=bee.require_approval,
                )
            ],
        )

        invoke_input: Any = Command(resume=resume_payload) if resume_payload is not None else {"messages": [("user", prompt or "")]}
        result = await agent.ainvoke(
            invoke_input,
            config={"configurable": {"thread_id": thread_id}, "callbacks": [trace_handler]},
        )

        interrupts = result.get("__interrupt__", []) if isinstance(result, dict) else []
        awaiting = bool(interrupts)
        with session_scope() as session:
            run_obj = session.get(Run, run_id)
            if run_obj:
                run_obj.status = "awaiting_approval" if awaiting else "completed"
                run_obj.completed_at = None if awaiting else datetime.now(timezone.utc)
                run_obj.artifacts_dir = str(art_path.resolve())

        if not awaiting:
            emit_trace_event(
                HiveTraceEvent(
                    thread_id=thread_id,
                    hive_name=bee.name,
                    run_id=run_id,
                    event_type="HIVE_COMPLETE",
                    source="system",
                    target="user",
                    payload={"project_root": str(art_path.resolve())},
                ),
                traces_dir,
            )
    except Exception as exc:
        logger.exception("Web bee run failed for thread %s: %s", thread_id, exc)
        emit_trace_event(
            HiveTraceEvent(
                thread_id=thread_id,
                hive_name=bee.name,
                run_id=run_id,
                event_type="HIVE_ERROR",
                source=bee.name,
                target="user",
                payload={"error": str(exc)},
            ),
            traces_dir,
        )
        with session_scope() as session:
            run_obj = session.get(Run, run_id)
            if run_obj:
                run_obj.status = "failed"
                run_obj.completed_at = datetime.now(timezone.utc)
    finally:
        await stack.aclose()


# ---------------------------------------------------------------------------
# FastAPI App Factory
# ---------------------------------------------------------------------------


def create_web_app(read_only: bool = False) -> FastAPI:
    """Create the FastAPI web application serving API + bundled SPA."""
    app = FastAPI(
        title="hobees Web UI",
        description="Visual Trace Explorer & Hive Studio",
        version=_package_version(),
    )

    static_dir = Path(__file__).parent / "static"
    assets_dir = static_dir / "assets"

    # Centralized Read-Only Guard Middleware
    @app.middleware("http")
    async def read_only_guard(request: Request, call_next):
        if (
            read_only
            and request.url.path.startswith("/api/v1")
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            return JSONResponse(
                {"detail": "Read-only mode is enabled; mutating operations are disabled."},
                status_code=403,
            )
        return await call_next(request)

    # Static assets mounts (MUST be registered before SPA fallback)
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        fav = static_dir / "favicon.svg"
        if fav.is_file():
            return FileResponse(fav, media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="Not found")

    # --- Status & Containers ---

    @app.get("/api/v1/status", response_model=StatusResponse)
    async def get_status():
        container = resolve_container_name()
        engine = get_engine()
        backend = get_database_backend(engine.url)
        return StatusResponse(
            status="ok",
            timestamp=datetime.now(timezone.utc),
            database=backend,
            container=container,
            read_only=read_only,
            version=_package_version(),
        )

    @app.get("/api/v1/containers", response_model=ContainerListResponse)
    async def list_containers():
        containers: set[str] = {resolve_container_name()}
        with session_scope() as session:
            run_c = session.query(Run.container_name).distinct().all()
            app_c = session.query(ApprovalEvent.container_name).distinct().all()
            for (name,) in run_c:
                if name:
                    containers.add(name)
            for (name,) in app_c:
                if name:
                    containers.add(name)
        return ContainerListResponse(containers=sorted(containers))

    # --- Providers ---

    @app.get("/api/v1/providers", response_model=list[ProviderResponse])
    async def list_providers():
        with session_scope() as session:
            providers = session.query(LLMProvider).order_by(LLMProvider.alias).all()
            return [_serialize_provider(p) for p in providers]

    @app.post("/api/v1/providers", response_model=ProviderResponse)
    async def create_provider(provider: ProviderCreate):
        with session_scope() as session:
            if session.query(LLMProvider).filter_by(alias=provider.alias).first():
                raise HTTPException(400, f"Provider '{provider.alias}' already exists")
            new_provider = LLMProvider(
                alias=provider.alias,
                provider_type=provider.provider_type,
                base_url=provider.base_url or None,
                api_key_env=provider.api_key_env or "NONE",
                default_model=provider.default_model or None,
                assistant_model=provider.assistant_model or None,
                input_cost_per_1m=provider.input_cost_per_1m,
                output_cost_per_1m=provider.output_cost_per_1m,
                context_window_tokens=provider.context_window_tokens,
            )
            session.add(new_provider)
            session.flush()
            return _serialize_provider(new_provider)

    @app.put("/api/v1/providers/{alias}", response_model=ProviderResponse)
    async def update_provider(alias: str, update: ProviderUpdate):
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=alias).first()
            if not provider:
                raise HTTPException(404, f"Provider '{alias}' not found")
            for field, value in update.model_dump(exclude_unset=True).items():
                setattr(provider, field, value)
            session.flush()
            return _serialize_provider(provider)

    @app.delete("/api/v1/providers/{alias}")
    async def delete_provider(alias: str):
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=alias).first()
            if not provider:
                raise HTTPException(404, f"Provider '{alias}' not found")
            if provider.bees or provider.supervised_hives:
                raise HTTPException(
                    400,
                    f"Provider '{alias}' is referenced by existing Bees or Hives and cannot be deleted.",
                )
            session.delete(provider)
            return {"success": True}

    # --- Bees ---

    @app.get("/api/v1/bees", response_model=list[BeeResponse])
    async def list_bees():
        with session_scope() as session:
            bees = session.query(Bee).order_by(Bee.name).all()
            return [_serialize_bee(b) for b in bees]

    @app.post("/api/v1/bees", response_model=BeeResponse)
    async def create_bee(bee: BeeCreate):
        with session_scope() as session:
            if session.query(Bee).filter_by(name=bee.name).first():
                raise HTTPException(400, f"Bee '{bee.name}' already exists")
            provider = session.get(LLMProvider, bee.provider_id)
            if not provider:
                raise HTTPException(400, f"Provider {bee.provider_id} not found")
            new_bee = Bee(
                name=bee.name,
                role_description=bee.role_description,
                system_prompt=bee.system_prompt,
                provider_id=bee.provider_id,
                model_name=bee.model_name,
                temperature=bee.temperature,
                thinking_level=bee.thinking_level,
                tool_names=bee.tool_names,
                require_approval=bee.require_approval,
            )
            session.add(new_bee)
            session.flush()
            session.refresh(new_bee)
            return _serialize_bee(new_bee)

    @app.put("/api/v1/bees/{name}", response_model=BeeResponse)
    async def update_bee(name: str, update: BeeUpdate):
        with session_scope() as session:
            bee = session.query(Bee).filter_by(name=name).first()
            if not bee:
                raise HTTPException(404, f"Bee '{name}' not found")
            for field, value in update.model_dump(exclude_unset=True).items():
                setattr(bee, field, value)
            session.flush()
            session.refresh(bee)
            return _serialize_bee(bee)

    @app.delete("/api/v1/bees/{name}")
    async def delete_bee(name: str):
        with session_scope() as session:
            bee = session.query(Bee).filter_by(name=name).first()
            if not bee:
                raise HTTPException(404, f"Bee '{name}' not found")
            session.delete(bee)
            return {"success": True}

    # --- Hives ---

    @app.get("/api/v1/hives", response_model=list[HiveResponse])
    async def list_hives():
        with session_scope() as session:
            hives = session.query(Hive).order_by(Hive.name).all()
            return [_serialize_hive(h) for h in hives]

    @app.post("/api/v1/hives", response_model=HiveResponse)
    async def create_hive(hive: HiveCreate):
        with session_scope() as session:
            if session.query(Hive).filter_by(name=hive.name).first():
                raise HTTPException(400, f"Hive '{hive.name}' already exists")
            provider = session.get(LLMProvider, hive.supervisor_provider_id)
            if not provider:
                raise HTTPException(400, f"Provider {hive.supervisor_provider_id} not found")
            new_hive = Hive(
                name=hive.name,
                goal_description=hive.goal_description or None,
                supervisor_provider_id=hive.supervisor_provider_id,
                supervisor_model_name=hive.supervisor_model_name,
                supervisor_prompt=hive.supervisor_prompt or None,
                supervisor_thinking_level=hive.supervisor_thinking_level,
                is_dynamic=hive.is_dynamic,
                project_path=hive.project_path or None,
            )
            session.add(new_hive)
            session.flush()
            for bee_id in hive.bee_ids:
                if session.get(Bee, bee_id):
                    session.add(HiveMembership(hive_id=new_hive.id, bee_id=bee_id))
            session.flush()
            session.refresh(new_hive)
            return _serialize_hive(new_hive)

    @app.put("/api/v1/hives/{name}", response_model=HiveResponse)
    async def update_hive(name: str, update: HiveUpdate):
        with session_scope() as session:
            hive = session.query(Hive).filter_by(name=name).first()
            if not hive:
                raise HTTPException(404, f"Hive '{name}' not found")
            for field, value in update.model_dump(exclude_unset=True).items():
                if field == "bee_ids":
                    session.query(HiveMembership).filter_by(hive_id=hive.id).delete()
                    for bee_id in value or []:
                        if session.get(Bee, bee_id):
                            session.add(HiveMembership(hive_id=hive.id, bee_id=bee_id))
                else:
                    setattr(hive, field, value)
            session.flush()
            session.refresh(hive)
            return _serialize_hive(hive)

    @app.delete("/api/v1/hives/{name}")
    async def delete_hive(name: str):
        with session_scope() as session:
            hive = session.query(Hive).filter_by(name=name).first()
            if not hive:
                raise HTTPException(404, f"Hive '{name}' not found")
            session.delete(hive)
            return {"success": True}

    # --- Tools ---

    @app.get("/api/v1/tools", response_model=ToolsResponse)
    async def list_tools():
        from hobees.core.tool_registry import TOOL_REGISTRY

        items: list[ToolSchema] = []
        for name, tool_obj in sorted(TOOL_REGISTRY.items()):
            params: dict[str, Any] = {}
            args_schema = getattr(tool_obj, "args_schema", None)
            if args_schema is not None:
                if hasattr(args_schema, "model_json_schema"):
                    params = args_schema.model_json_schema()
                elif hasattr(args_schema, "schema"):
                    params = args_schema.schema()
            items.append(
                ToolSchema(
                    name=name,
                    description=(getattr(tool_obj, "description", "") or "").strip(),
                    parameters=params,
                )
            )
        return ToolsResponse(tools=items)

    # --- Skills ---

    @app.get("/api/v1/skills", response_model=list[SkillResponse])
    async def list_skills():
        with session_scope() as session:
            skills = session.query(Skill).order_by(Skill.name).all()
            return [
                SkillResponse(
                    id=s.id,
                    name=s.name,
                    description=s.description,
                    instructions=s.instructions,
                    tags=list(s.tags or []),
                    source_thread_id=s.source_thread_id,
                    usage_count=s.usage_count or 0,
                )
                for s in skills
            ]

    @app.post("/api/v1/skills/save-last", response_model=SkillResponse)
    async def save_last_skill():
        from hobees.core.skill_harvester import harvest_completed_run

        with session_scope() as session:
            run = session.query(Run).order_by(Run.id.desc()).first()
            if not run:
                raise HTTPException(404, "No runs found")
            draft = run.suggested_skill_draft
            run_id = run.id
            source_thread_id = run.thread_id

        if not draft:
            draft = harvest_completed_run(run_id)
        if not draft:
            raise HTTPException(400, "No reusable skill draft could be generated from the last run.")

        with session_scope() as session:
            existing = session.query(Skill).filter_by(name=draft["name"]).first()
            if existing:
                existing.description = draft["description"]
                existing.instructions = draft["instructions"]
                existing.tags = draft.get("tags", [])
                existing.source_thread_id = source_thread_id
                skill = existing
            else:
                skill = Skill(
                    name=draft["name"],
                    description=draft["description"],
                    instructions=draft["instructions"],
                    tags=draft.get("tags", []),
                    source_thread_id=source_thread_id,
                )
                session.add(skill)
            session.flush()
            return SkillResponse(
                id=skill.id,
                name=skill.name,
                description=skill.description,
                instructions=skill.instructions,
                tags=list(skill.tags or []),
                source_thread_id=skill.source_thread_id,
                usage_count=skill.usage_count or 0,
            )

    @app.delete("/api/v1/skills/{name}")
    async def delete_skill(name: str):
        with session_scope() as session:
            skill = session.query(Skill).filter_by(name=name).first()
            if not skill:
                raise HTTPException(404, f"Skill '{name}' not found")
            session.delete(skill)
            return {"success": True}

    # --- Declarative YAML Export / Import (100% compatible with hobees import) ---

    @app.get("/api/v1/config/yaml", response_model=ConfigYamlResponse)
    async def export_config():
        import yaml

        with session_scope() as session:
            providers = session.query(LLMProvider).order_by(LLMProvider.alias).all()
            bees = session.query(Bee).order_by(Bee.name).all()
            hives = session.query(Hive).order_by(Hive.name).all()
            skills = session.query(Skill).order_by(Skill.name).all()
            memories = session.query(Memory).order_by(Memory.namespace, Memory.key).all()

            config: dict[str, Any] = {
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
                config["skills"] = [
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
                config["memory"] = [
                    {
                        "namespace": m.namespace,
                        "key": m.key,
                        "content": m.content,
                    }
                    for m in memories
                ]

        return ConfigYamlResponse(yaml=yaml.safe_dump(config, sort_keys=False, allow_unicode=True))

    @app.post("/api/v1/config/yaml")
    async def import_config_yaml(yaml_text: str = Body(..., media_type="text/plain")):
        import yaml
        from hobees.cli.import_cmd import import_config

        try:
            parsed = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"Invalid YAML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(400, "YAML root must be a mapping with providers/bees/hives.")

        # Windows-safe temporary file: close before passing to import_config and unlinking.
        fd, tmp_name = tempfile.mkstemp(suffix=".yaml", text=True)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(yaml_text)
            import_config(tmp_path, dry_run=False, force=True)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Failed to import YAML config: {exc}") from exc
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        return {"success": True}

    # --- Runs ---

    @app.post("/api/v1/runs", response_model=RunResponse)
    async def create_run(run: RunCreate):
        if run.approval_mode and run.approval_mode not in APPROVAL_MODES:
            raise HTTPException(400, f"Invalid approval_mode '{run.approval_mode}'. Choose {', '.join(APPROVAL_MODES)}.")

        container = resolve_container_name(run.container_name)
        entity_name = run.entity_name or "default"
        thread_id = resolve_thread_id(run.scope, entity_name, run.thread_id, container)

        hive_id: int | None = None
        bee_id: int | None = None

        with session_scope() as session:
            if run.scope == "hive":
                hive = session.query(Hive).filter_by(name=entity_name).first()
                if not hive:
                    raise HTTPException(404, f"Hive '{entity_name}' not found")
                if not [m.bee for m in (hive.memberships or []) if m.bee]:
                    raise HTTPException(400, f"Hive '{entity_name}' has no member Bees.")
                hive_id = hive.id
            elif run.scope == "bee":
                bee = session.query(Bee).filter_by(name=entity_name).first()
                if not bee:
                    raise HTTPException(404, f"Bee '{entity_name}' not found")
                bee_id = bee.id
            else:  # assistant
                assistant = session.query(Bee).filter_by(name="assistant").first()
                if not assistant:
                    provider = session.query(LLMProvider).order_by(LLMProvider.id).first()
                    if not provider:
                        raise HTTPException(400, "No LLM providers configured. Add a provider in Hive Studio first.")
                    assistant = Bee(
                        name="assistant",
                        role_description="General-purpose assistant.",
                        system_prompt="You are a helpful AI assistant.",
                        provider_id=provider.id,
                        model_name=provider.assistant_model or provider.default_model or "gpt-4o-mini",
                        temperature=0.7,
                        thinking_level="off",
                        tool_names=["read_file", "write_file", "list_directory", "run_python_calc", "save_memory", "recall_memory"],
                    )
                    session.add(assistant)
                    session.flush()
                bee_id = assistant.id

            existing_run = session.query(Run).filter_by(thread_id=thread_id).first()
            now = datetime.now(timezone.utc)
            if existing_run:
                existing_run.status = "running"
                existing_run.goal = run.prompt
                existing_run.container_name = container
                existing_run.completed_at = None
                run_id = existing_run.id
            else:
                run_obj = Run(
                    thread_id=thread_id,
                    container_name=container,
                    hive_id=hive_id,
                    mode=run.scope,
                    goal=run.prompt,
                    status="running",
                    started_at=now,
                )
                session.add(run_obj)
                session.flush()
                run_id = run_obj.id

        if run.scope == "hive" and hive_id is not None:
            asyncio.create_task(
                _run_hive_graph_task(
                    hive_id=hive_id,
                    thread_id=thread_id,
                    run_id=run_id,
                    prompt=run.prompt,
                    approval_mode=run.approval_mode,
                    thinking=run.thinking,
                    container_name=container,
                )
            )
        elif bee_id is not None:
            asyncio.create_task(
                _run_single_bee_task(
                    bee_id=bee_id,
                    thread_id=thread_id,
                    run_id=run_id,
                    prompt=run.prompt,
                    approval_mode=run.approval_mode,
                    thinking=run.thinking,
                    container_name=container,
                )
            )

        return RunResponse(thread_id=thread_id, status="running")

    # --- Traces ---

    @app.get("/api/v1/traces", response_model=list[TraceSummaryItem])
    async def list_traces(
        container: Optional[str] = None,
        hive: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        with session_scope() as session:
            hives_by_id = {h.id: h.name for h in session.query(Hive).all()}
            query = session.query(Run)
            if container and container != "all":
                query = query.filter(Run.container_name == container)
            if hive:
                hive_obj = session.query(Hive).filter_by(name=hive).first()
                if hive_obj:
                    query = query.filter(Run.hive_id == hive_obj.id)
                else:
                    return []
            if status and status != "all":
                query = query.filter(Run.status == status)
            if q:
                like = f"%{q}%"
                query = query.filter((Run.thread_id.ilike(like)) | (Run.goal.ilike(like)))

            runs = query.order_by(desc(Run.started_at), desc(Run.id)).offset(offset).limit(limit).all()
            thread_ids = [r.thread_id for r in runs]

            usage_map: dict[str, tuple[int, int, float]] = {}
            pending_map: dict[str, int] = {}
            if thread_ids:
                usage_agg = (
                    session.query(
                        UsageEvent.thread_id,
                        func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                        func.coalesce(func.sum(UsageEvent.output_tokens), 0),
                        func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0.0),
                    )
                    .filter(UsageEvent.thread_id.in_(thread_ids))
                    .group_by(UsageEvent.thread_id)
                    .all()
                )
                for tid, in_tok, out_tok, cost in usage_agg:
                    usage_map[tid] = (int(in_tok or 0), int(out_tok or 0), float(cost or 0.0))

                pending_agg = (
                    session.query(ApprovalEvent.thread_id, func.count(ApprovalEvent.id))
                    .filter(ApprovalEvent.thread_id.in_(thread_ids), ApprovalEvent.decision == "pending")
                    .group_by(ApprovalEvent.thread_id)
                    .all()
                )
                for tid, cnt in pending_agg:
                    pending_map[tid] = int(cnt)

            items: list[TraceSummaryItem] = []
            for r in runs:
                in_tok, out_tok, cost = usage_map.get(r.thread_id, (0, 0, 0.0))
                pending_count = pending_map.get(r.thread_id, 0)
                hive_name = hives_by_id.get(r.hive_id) if r.hive_id else None
                duration_ms = None
                if r.started_at and r.completed_at:
                    s = r.started_at if r.started_at.tzinfo else r.started_at.replace(tzinfo=timezone.utc)
                    e = r.completed_at if r.completed_at.tzinfo else r.completed_at.replace(tzinfo=timezone.utc)
                    duration_ms = max(0, int((e - s).total_seconds() * 1000))
                effective_status = "awaiting_approval" if pending_count > 0 and r.status != "failed" else r.status
                items.append(
                    TraceSummaryItem(
                        container=r.container_name or "local",
                        thread_id=r.thread_id,
                        status=effective_status,
                        mode=r.mode,
                        goal=r.goal,
                        hive_name=hive_name,
                        entity_name=_entity_from_thread(r.thread_id, hive_name),
                        total_tokens=in_tok + out_tok,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        estimated_cost_usd=cost,
                        duration_ms=duration_ms,
                        pending_approvals=pending_count,
                        started_at=r.started_at,
                        completed_at=r.completed_at,
                    )
                )
            return items

    @app.get("/api/v1/traces/{thread_id}", response_model=TraceDetailResponse)
    async def get_trace(thread_id: str):
        extra_roots: list[Path] = []
        with session_scope() as session:
            run = session.query(Run).filter_by(thread_id=thread_id).first()
            approvals = (
                session.query(ApprovalEvent)
                .filter_by(thread_id=thread_id)
                .order_by(ApprovalEvent.requested_at.asc(), ApprovalEvent.id.asc())
                .all()
            )
            usage_rows = (
                session.query(UsageEvent)
                .filter_by(thread_id=thread_id)
                .order_by(UsageEvent.created_at.asc(), UsageEvent.id.asc())
                .all()
            )
            if not run and not approvals and not usage_rows:
                raise HTTPException(404, f"Thread '{thread_id}' not found")

            hive_name = None
            hive_id = run.hive_id if run else None
            if hive_id:
                hive = session.get(Hive, hive_id)
                if hive:
                    hive_name = hive.name
                    if hive.project_path:
                        extra_roots.append(Path(hive.project_path))
            if run and run.artifacts_dir:
                extra_roots.append(Path(run.artifacts_dir))

            approval_records = [_serialize_approval(a) for a in approvals]
            container = (
                (run.container_name if run and run.container_name else None)
                or (approvals[0].container_name if approvals else None)
                or "local"
            )
            in_tok = sum(u.input_tokens or 0 for u in usage_rows)
            out_tok = sum(u.output_tokens or 0 for u in usage_rows)
            cost = sum(float(u.estimated_cost_usd or 0.0) for u in usage_rows)
            latency_ms = sum(u.latency_ms or 0 for u in usage_rows)
            status = run.status if run else "unknown"
            if any(a.decision == "pending" for a in approval_records) and status != "failed":
                status = "awaiting_approval"

        trace_events = _load_trace_events(thread_id, extra_roots=extra_roots)
        checkpoints = await _load_checkpoint_snapshots(thread_id, hive_id)
        nodes = _build_unified_trace_nodes(trace_events, approval_records, usage_rows, checkpoints)

        return TraceDetailResponse(
            container=container,
            thread_id=thread_id,
            status=status,
            mode=run.mode if run else _scope_from_thread(thread_id),
            goal=run.goal if run else "",
            hive_name=hive_name,
            entity_name=_entity_from_thread(thread_id, hive_name),
            total_tokens=in_tok + out_tok,
            input_tokens=in_tok,
            output_tokens=out_tok,
            estimated_cost_usd=cost,
            total_latency_ms=latency_ms,
            started_at=run.started_at if run else None,
            completed_at=run.completed_at if run else None,
            has_checkpoints=bool(checkpoints),
            nodes=nodes,
            approvals=approval_records,
            events=trace_events,
        )

    @app.post("/api/v1/traces/{thread_id}/replay", response_model=ReplayResponse)
    async def replay_trace(thread_id: str, request: ReplayRequest):
        with session_scope() as session:
            run = session.query(Run).filter_by(thread_id=thread_id).first()
            if not run:
                raise HTTPException(404, f"Thread '{thread_id}' not found")
            if not run.hive_id:
                raise HTTPException(400, "Checkpoint replay is currently supported for Hive threads.")
            hive_id = run.hive_id
            container = run.container_name or resolve_container_name()
            run_id = run.id

        checkpoints = await _load_checkpoint_snapshots(thread_id, hive_id)
        if not any(cp.get("checkpoint_id") == request.checkpoint_id for cp in checkpoints):
            raise HTTPException(404, f"Checkpoint '{request.checkpoint_id}' not found for thread '{thread_id}'.")

        with session_scope() as session:
            run_obj = session.get(Run, run_id)
            if run_obj:
                run_obj.status = "running"
                run_obj.completed_at = None

        asyncio.create_task(
            _run_hive_graph_task(
                hive_id=hive_id,
                thread_id=thread_id,
                run_id=run_id,
                prompt=None,
                approval_mode=request.approval_mode,
                thinking=None,
                container_name=container,
                replay_checkpoint_id=request.checkpoint_id,
                patch_message=request.patch_message,
            )
        )

        return ReplayResponse(
            thread_id=thread_id,
            forked_from=request.checkpoint_id,
            status="running",
        )

    # --- Approvals ---

    @app.get("/api/v1/approvals", response_model=ApprovalListResponse)
    async def list_approvals(
        status: Optional[str] = None,
        container: Optional[str] = None,
    ):
        with session_scope() as session:
            query = session.query(ApprovalEvent)
            if status and status != "all":
                query = query.filter(ApprovalEvent.decision == status)
            if container and container != "all":
                query = query.filter(ApprovalEvent.container_name == container)
            approvals = query.order_by(desc(ApprovalEvent.requested_at), desc(ApprovalEvent.id)).limit(100).all()
            return ApprovalListResponse(approvals=[_serialize_approval(a) for a in approvals])

    @app.post("/api/v1/approvals/{approval_id}/resolve", response_model=ApprovalResolveResponse)
    async def resolve_approval(approval_id: int, request: ApprovalResolveRequest):
        now = datetime.now(timezone.utc)
        hive_id: int | None = None
        bee_id: int | None = None
        run_id: int | None = None

        with session_scope() as session:
            approval = session.get(ApprovalEvent, approval_id)
            if not approval:
                raise HTTPException(404, f"Approval {approval_id} not found")
            if approval.decision != "pending":
                raise HTTPException(400, f"Approval already resolved: {approval.decision}")

            original_args = _parse_json_obj(approval.original_args_json)
            if request.action == "edit":
                if request.args is None:
                    raise HTTPException(400, "Edited 'args' object is required when action == 'edit'.")
                approval.final_args_json = json.dumps(request.args, sort_keys=True)
            elif request.action == "approve":
                approval.final_args_json = json.dumps(original_args, sort_keys=True)
            else:
                approval.final_args_json = None
                approval.reason = request.reason or "Rejected by operator."

            approval.decision = request.action
            approval.resolved_at = now
            thread_id = approval.thread_id
            checkpoint_id = approval.checkpoint_id or ""
            container = approval.container_name
            approval_mode = approval.approval_mode

            run = session.query(Run).filter_by(thread_id=thread_id).first()
            if run:
                run_id = run.id
                hive_id = run.hive_id
                if not hive_id:
                    bee = session.query(Bee).filter_by(name=approval.bee_name).first()
                    bee_id = bee.id if bee else None

        resume_payload: dict[str, Any] = {"action": request.action}
        if request.action == "edit":
            resume_payload["args"] = request.args
        elif request.action == "reject":
            resume_payload["reason"] = request.reason or "Rejected by operator."

        resumed = False
        checkpoints = await _load_checkpoint_snapshots(thread_id, hive_id)
        if checkpoints and run_id is not None:
            if hive_id is not None:
                with session_scope() as session:
                    run_obj = session.get(Run, run_id)
                    if run_obj:
                        run_obj.status = "running"
                asyncio.create_task(
                    _run_hive_graph_task(
                        hive_id=hive_id,
                        thread_id=thread_id,
                        run_id=run_id,
                        prompt=None,
                        approval_mode=approval_mode,
                        thinking=None,
                        container_name=container,
                        resume_payload=resume_payload,
                    )
                )
                resumed = True
            elif bee_id is not None:
                with session_scope() as session:
                    run_obj = session.get(Run, run_id)
                    if run_obj:
                        run_obj.status = "running"
                asyncio.create_task(
                    _run_single_bee_task(
                        bee_id=bee_id,
                        thread_id=thread_id,
                        run_id=run_id,
                        prompt=None,
                        approval_mode=approval_mode,
                        thinking=None,
                        container_name=container,
                        resume_payload=resume_payload,
                    )
                )
                resumed = True

        return ApprovalResolveResponse(
            success=True,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            resumed=resumed,
            status="running" if resumed else "resolved",
        )

    # --- Memories ---

    @app.get("/api/v1/memories", response_model=MemoryListResponse)
    async def list_memories(
        namespace: Optional[str] = None,
        q: Optional[str] = None,
    ):
        with session_scope() as session:
            all_ns = sorted(
                {ns for (ns,) in session.query(Memory.namespace).distinct().all() if ns}
                | {"global"}
                | {f"hive:{h.name}" for h in session.query(Hive).all()}
                | {f"bee:{b.name}" for b in session.query(Bee).all()}
            )
            query = session.query(Memory)
            if namespace and namespace != "all":
                if namespace.endswith(":"):
                    query = query.filter(Memory.namespace.like(f"{namespace}%"))
                else:
                    query = query.filter(Memory.namespace == namespace)
            if q:
                like = f"%{q}%"
                query = query.filter(
                    (Memory.key.ilike(like))
                    | (Memory.content.ilike(like))
                    | (Memory.namespace.ilike(like))
                )
            rows = query.order_by(desc(Memory.updated_at), desc(Memory.id)).limit(200).all()
            return MemoryListResponse(
                memories=[
                    MemoryItem(
                        id=m.id,
                        namespace=m.namespace,
                        key=m.key,
                        content=m.content,
                        source_thread_id=m.source_thread_id,
                        updated_at=m.updated_at,
                    )
                    for m in rows
                ],
                namespaces=all_ns,
            )

    @app.post("/api/v1/memories")
    async def upsert_memory(memory: MemoryCreate):
        with session_scope() as session:
            existing = session.query(Memory).filter_by(
                namespace=memory.namespace, key=memory.key
            ).first()
            if existing:
                existing.content = memory.content
                existing.updated_at = datetime.now(timezone.utc)
            else:
                session.add(
                    Memory(
                        namespace=memory.namespace,
                        key=memory.key,
                        content=memory.content,
                    )
                )
            return {"success": True}

    @app.delete("/api/v1/memories/{memory_id}")
    async def delete_memory(memory_id: int):
        with session_scope() as session:
            memory = session.get(Memory, memory_id)
            if not memory:
                raise HTTPException(404, "Memory not found")
            session.delete(memory)
            return {"success": True}

    # --- Artifacts ---

    def _artifact_base(hive: Optional[str]) -> Path:
        if hive:
            with session_scope() as session:
                h = session.query(Hive).filter_by(name=hive).first()
                if h and h.project_path:
                    out = Path(h.project_path) / "output"
                    return out if out.exists() else Path(h.project_path)
            out = settings.artifacts_root / hive / "output"
            return out if out.exists() else settings.artifacts_root / hive
        return settings.artifacts_root

    @app.get("/api/v1/artifacts", response_model=ArtifactListResponse)
    async def list_artifacts(hive: Optional[str] = None):
        base = _artifact_base(hive)
        hives_found: set[str] = set()
        if settings.artifacts_root.exists():
            for child in settings.artifacts_root.iterdir():
                if child.is_dir():
                    hives_found.add(child.name)
        with session_scope() as session:
            for h in session.query(Hive).all():
                hives_found.add(h.name)

        artifacts: list[ArtifactItem] = []
        if base.exists():
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(base)
                # Exclude internal trace JSONL files from output artifact browser
                if "traces" in rel.parts:
                    continue
                item_hive = hive or (rel.parts[0] if len(rel.parts) > 1 else None)
                stat = path.stat()
                artifacts.append(
                    ArtifactItem(
                        path=rel.as_posix(),
                        name=path.name,
                        hive=item_hive,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    )
                )
        return ArtifactListResponse(artifacts=artifacts, hives=sorted(hives_found))

    @app.get("/api/v1/artifacts/content")
    async def get_artifact_content(
        path: str,
        hive: Optional[str] = None,
        download: bool = Query(False),
    ):
        base = _artifact_base(hive).resolve()
        file_path = (base / path).resolve()
        if not file_path.is_relative_to(base):
            raise HTTPException(403, "Invalid artifact path")
        if not file_path.is_file():
            raise HTTPException(404, "Artifact not found")
        if download:
            return FileResponse(file_path, filename=file_path.name)
        return FileResponse(file_path)

    # --- SSE Streams ---

    @app.get("/api/v1/runs/{thread_id}/stream")
    async def run_trace_stream(
        thread_id: str,
        request: Request,
        timeout: Optional[float] = Query(None, ge=0.1),
    ):
        broker = EventBroker.get_instance()
        q = broker.subscribe()

        async def trace_generator():
            try:
                seen: set[str] = set()
                terminal_seen = False
                for ev in _load_trace_events(thread_id):
                    key = json.dumps(ev, sort_keys=True)
                    if key in seen:
                        continue
                    seen.add(key)
                    if ev.get("event_type") in ("HIVE_COMPLETE", "HIVE_ERROR"):
                        terminal_seen = True
                    yield f"data: {json.dumps(ev)}\n\n"

                with session_scope() as session:
                    run_obj = session.query(Run).filter_by(thread_id=thread_id).first()
                    run_status = run_obj.status if run_obj else None

                if (terminal_seen and run_status != "running") or run_status in ("completed", "failed"):
                    return

                idle_since = asyncio.get_running_loop().time()
                last_keep_alive = idle_since
                while True:
                    if await request.is_disconnected():
                        return
                    now = asyncio.get_running_loop().time()
                    wait_time = 0.25
                    if timeout is not None:
                        remaining = timeout - (now - idle_since)
                        if remaining <= 0:
                            return
                        wait_time = min(wait_time, remaining)
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=wait_time)
                    except asyncio.TimeoutError:
                        ev = None
                    if ev is not None and ev.get("thread_id") == thread_id:
                        key = json.dumps(ev, sort_keys=True)
                        if key not in seen:
                            seen.add(key)
                            yield f"data: {json.dumps(ev)}\n\n"
                        idle_since = asyncio.get_running_loop().time()
                        if ev.get("event_type") in ("HIVE_COMPLETE", "HIVE_ERROR"):
                            return
                    if now - last_keep_alive >= 15:
                        yield ": keep-alive\n\n"
                        last_keep_alive = now
            finally:
                broker.unsubscribe(q)

        return StreamingResponse(trace_generator(), media_type="text/event-stream")

    # --- SPA Catch-All (MUST BE LAST) ---

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str = ""):
        # Never serve HTML for missing API or static asset requests
        if path.startswith(("api/", "assets/", "static/")) or path in {"api", "assets", "static"}:
            raise HTTPException(status_code=404, detail="Not found")
        index_path = static_dir / "index.html"
        if index_path.is_file():
            return FileResponse(index_path, media_type="text/html")
        return JSONResponse(
            {"message": "hobees Web UI static bundle not found. Run `npm run build` in web-ui/.", "api_docs": "/docs"},
            status_code=503,
        )

    return app


__all__ = ["create_web_app"]
