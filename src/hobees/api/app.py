"""FastAPI telemetry API for hobees (Phase 6)."""

from __future__ import annotations

import json
import asyncio
from importlib.metadata import version as package_version
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

from hobees.db.analytics import summary, recent_events, active_runs, run_thread_usage, Window
from hobees.db.session import session_scope
from hobees.db.models import LLMProvider, Bee, Hive, Run


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime


class StatsResponse(BaseModel):
    window: str
    group_by: str
    data: list[dict]
    totals: dict


class RecentEventsResponse(BaseModel):
    events: list[dict]


class ActiveRunsResponse(BaseModel):
    runs: list[dict]


class RunThreadResponse(BaseModel):
    thread_id: str
    usage: dict


class ProviderRosterItem(BaseModel):
    id: int
    alias: str
    provider_type: str
    default_model: Optional[str] = None
    available_models: list[str] = []


class BeeRosterItem(BaseModel):
    id: int
    name: str
    role_description: str
    model_name: str
    thinking_level: str
    tool_names: list[str] = []


class HiveRosterItem(BaseModel):
    id: int
    name: str
    goal_description: Optional[str] = None
    supervisor_model_name: Optional[str] = None
    is_dynamic: bool
    bee_names: list[str] = []


class RosterResponse(BaseModel):
    providers: list[ProviderRosterItem]
    bees: list[BeeRosterItem]
    hives: list[HiveRosterItem]


class RunItem(BaseModel):
    id: int
    thread_id: str
    hive_id: Optional[int] = None
    mode: str
    goal: Optional[str] = None
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    compacted_count: int = 0


class RunsResponse(BaseModel):
    runs: list[RunItem]


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="hobees Telemetry API",
        description="Usage insights and telemetry for hobees multi-agent orchestrator",
        version=package_version("hobees"),
    )

    @app.get("/health", response_model=HealthResponse)
    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(status="ok", timestamp=datetime.now())

    @app.get("/stats", response_model=StatsResponse)
    @app.get("/api/stats", response_model=StatsResponse)
    async def stats(
        window: Window = Query("all", description="Time window: 1h, 24h, 7d, all"),
        group_by: Literal["bee", "hive", "provider", "day"] = Query("bee", description="Group by"),
    ) -> StatsResponse:
        """Get aggregated usage statistics."""
        data = summary(window=window, group_by=group_by)

        total_events = sum(row.get("events", 0) for row in data)
        total_in = sum(row.get("input_tokens", 0) for row in data)
        total_out = sum(row.get("output_tokens", 0) for row in data)
        total_cost = sum(row.get("estimated_cost_usd", 0.0) for row in data)

        return StatsResponse(
            window=window,
            group_by=group_by,
            data=data,
            totals={
                "events": total_events,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_in + total_out,
                "estimated_cost_usd": total_cost,
            },
        )

    @app.get("/stats/recent", response_model=RecentEventsResponse)
    @app.get("/api/stats/recent", response_model=RecentEventsResponse)
    async def stats_recent(limit: int = Query(20, ge=1, le=100)) -> RecentEventsResponse:
        """Get most recent usage events."""
        events = recent_events(limit=limit)
        return RecentEventsResponse(events=events)

    @app.get("/runs/active", response_model=ActiveRunsResponse)
    @app.get("/api/runs/active", response_model=ActiveRunsResponse)
    async def runs_active() -> ActiveRunsResponse:
        """Get currently running runs."""
        runs = active_runs()
        return ActiveRunsResponse(runs=runs)

    @app.get("/runs/{thread_id}", response_model=RunThreadResponse)
    @app.get("/api/runs/{thread_id}", response_model=RunThreadResponse)
    async def run_thread(thread_id: str) -> RunThreadResponse:
        """Get telemetry for a specific thread."""
        usage = run_thread_usage(thread_id)
        if not usage:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        return RunThreadResponse(thread_id=thread_id, usage=usage)

    @app.get("/roster", response_model=RosterResponse)
    @app.get("/api/roster", response_model=RosterResponse)
    async def roster() -> RosterResponse:
        """Get the global roster of providers, bees, and hives."""
        with session_scope() as session:
            providers = session.query(LLMProvider).all()
            bees = session.query(Bee).all()
            hives = session.query(Hive).all()

            prov_items = [
                ProviderRosterItem(
                    id=p.id,
                    alias=p.alias,
                    provider_type=p.provider_type,
                    default_model=p.default_model,
                    available_models=p.available_models or [],
                )
                for p in providers
            ]
            bee_items = [
                BeeRosterItem(
                    id=b.id,
                    name=b.name,
                    role_description=b.role_description,
                    model_name=b.model_name,
                    thinking_level=b.thinking_level or "off",
                    tool_names=b.tool_names or [],
                )
                for b in bees
            ]
            hive_items = [
                HiveRosterItem(
                    id=h.id,
                    name=h.name,
                    goal_description=h.goal_description,
                    supervisor_model_name=h.supervisor_model_name,
                    is_dynamic=h.is_dynamic,
                    bee_names=[m.bee.name for m in h.memberships if m.bee] if h.memberships else [],
                )
                for h in hives
            ]
            return RosterResponse(providers=prov_items, bees=bee_items, hives=hive_items)

    @app.get("/runs", response_model=RunsResponse)
    @app.get("/api/runs", response_model=RunsResponse)
    async def list_runs(
        status: Optional[str] = Query(None, description="Filter by status (e.g. running, completed, failed)"),
        limit: int = Query(50, ge=1, le=200, description="Max runs to return"),
    ) -> RunsResponse:
        """Get historical runs."""
        with session_scope() as session:
            q = session.query(Run)
            if status:
                q = q.filter_by(status=status)
            runs = q.order_by(Run.started_at.desc()).limit(limit).all()
            return RunsResponse(
                runs=[
                    RunItem(
                        id=r.id,
                        thread_id=r.thread_id,
                        hive_id=r.hive_id,
                        mode=r.mode,
                        goal=r.goal,
                        status=r.status,
                        started_at=r.started_at,
                        completed_at=r.completed_at,
                        compacted_count=r.compacted_count or 0,
                    )
                    for r in runs
                ]
            )

    @app.get("/usage/stream")
    @app.get("/api/usage/stream")
    async def usage_stream(
        limit: int = Query(20, ge=1, le=100, description="Initial events to yield"),
        poll_interval: float = Query(2.0, ge=0.2, le=10.0, description="Poll interval seconds"),
        iterations: int = Query(1, ge=1, le=100, description="Stream iterations"),
    ):
        """Server-Sent Events (SSE) stream of usage telemetry."""
        async def event_generator():
            for _ in range(iterations):
                events = recent_events(limit=limit)
                serialized = []
                for ev in events:
                    ev_copy = dict(ev)
                    if "created_at" in ev_copy and isinstance(ev_copy["created_at"], datetime):
                        ev_copy["created_at"] = ev_copy["created_at"].isoformat()
                    serialized.append(ev_copy)
                data = json.dumps({"events": serialized, "timestamp": datetime.now().isoformat()})
                yield f"data: {data}\n\n"
                if iterations > 1:
                    await asyncio.sleep(poll_interval)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/runs/{thread_id}/stream")
    @app.get("/api/runs/{thread_id}/stream")
    async def run_trace_stream(
        thread_id: str,
        request: Request,
        timeout: float | None = Query(
            None,
            ge=0.1,
            description="Optional maximum idle seconds before ending the live stream",
        ),
    ):
        """Server-Sent Events (SSE) stream of live and historical Hive trace events."""
        from hobees.core.tracing import EventBroker
        from hobees.config import settings

        broker = EventBroker.get_instance()
        q = broker.subscribe()
        with session_scope() as session:
            run = session.query(Run).filter_by(thread_id=thread_id).first()
            run_status = run.status if run else None
            artifacts_dir = run.artifacts_dir if run else None
            hive = session.get(Hive, run.hive_id) if run and run.hive_id else None
            hive_name = hive.name if hive else None
            project_path = hive.project_path if hive else None

        async def trace_generator():
            try:
                trace_paths = []
                if artifacts_dir:
                    trace_paths.append(Path(artifacts_dir) / "traces" / f"{thread_id}.jsonl")
                if project_path:
                    trace_paths.append(Path(project_path) / "traces" / f"{thread_id}.jsonl")
                if hive_name:
                    trace_paths.append(
                        settings.artifacts_root / hive_name / "traces" / f"{thread_id}.jsonl"
                    )
                else:
                    trace_paths.extend(
                        settings.artifacts_root.glob(f"*/traces/{thread_id}.jsonl")
                    )

                trace_paths = list(dict.fromkeys(trace_paths))
                file_offsets = {}
                seen_events = set()
                terminal_seen = False
                for trace_file in trace_paths:
                    if not trace_file.is_file():
                        continue
                    lines, file_offsets[trace_file] = _read_complete_trace_lines(
                        trace_file, 0
                    )
                    for line in lines:
                        serialized = line.decode("utf-8").strip()
                        if not serialized or serialized in seen_events:
                            continue
                        seen_events.add(serialized)
                        event = json.loads(serialized)
                        terminal_seen |= event.get("event_type") in (
                            "HIVE_COMPLETE",
                            "HIVE_ERROR",
                        )
                        yield f"data: {serialized}\n\n"

                if (
                    (terminal_seen and run_status != "running")
                    or run_status in ("completed", "failed")
                ):
                    return

                idle_since = asyncio.get_running_loop().time()
                last_keep_alive = idle_since
                last_status_check = idle_since
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
                        event = await asyncio.wait_for(q.get(), timeout=wait_time)
                    except asyncio.TimeoutError:
                        event = None
                    if event is not None and event.get("thread_id") == thread_id:
                        serialized = json.dumps(event)
                        if serialized not in seen_events:
                            seen_events.add(serialized)
                            yield f"data: {serialized}\n\n"
                        idle_since = asyncio.get_running_loop().time()
                        if event.get("event_type") in ("HIVE_COMPLETE", "HIVE_ERROR"):
                            return

                    for trace_file in trace_paths:
                        lines, file_offsets[trace_file] = _read_complete_trace_lines(
                            trace_file, file_offsets.get(trace_file, 0)
                        )
                        for line in lines:
                            serialized = line.decode("utf-8").strip()
                            if not serialized or serialized in seen_events:
                                continue
                            seen_events.add(serialized)
                            event = json.loads(serialized)
                            yield f"data: {serialized}\n\n"
                            idle_since = asyncio.get_running_loop().time()
                            if event.get("event_type") in (
                                "HIVE_COMPLETE",
                                "HIVE_ERROR",
                            ):
                                return
                    now = asyncio.get_running_loop().time()
                    if run_status == "running" and now - last_status_check >= 1:
                        last_status_check = now
                        with session_scope() as session:
                            current_run = session.query(Run).filter_by(
                                thread_id=thread_id
                            ).first()
                            if current_run and current_run.status in (
                                "completed",
                                "failed",
                            ):
                                return
                    if now - last_keep_alive >= 15:
                        yield ": keep-alive\n\n"
                        last_keep_alive = now
            finally:
                broker.unsubscribe(q)

        return StreamingResponse(trace_generator(), media_type="text/event-stream")

    return app


def _read_complete_trace_lines(path: Path, offset: int) -> tuple[list[bytes], int]:
    """Read only complete JSONL records, leaving a concurrent partial write for later."""
    try:
        with path.open("rb") as trace:
            trace.seek(offset)
            data = trace.read()
    except FileNotFoundError:
        return [], offset

    lines = data.splitlines(keepends=True)
    complete_lines = []
    consumed = 0
    for line in lines:
        if not line.endswith(b"\n"):
            break
        complete_lines.append(line)
        consumed += len(line)
    return complete_lines, offset + consumed


__all__ = ["create_app"]