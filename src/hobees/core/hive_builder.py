"""Dynamic Hive graph construction (FR-5).

Hydrates a Working Hive's Bees into ``create_agent`` workers, each bound
to its own LLM provider/model/tools with a ``TelemetryCallbackHandler``, and
delegates to them through supervisor tools.

v1.1 additions:
- Worker Context Isolation (state projection)
- Thinking level support
- Memory injection
- Progressive skill loading
- Rolling compaction
"""

from __future__ import annotations

import inspect
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Iterator

from langchain_core.runnables import RunnableConfig
from sqlalchemy.engine import URL

from hobees.core.llm_factory import get_chat_model
from hobees.core.telemetry import TelemetryCallbackHandler
from hobees.core.tool_registry import get_tools
from hobees.core.memory_manager import extract_namespaces, build_memory_block, get_memories_for_namespaces
from hobees.core.context_manager import project_worker_context, compact_messages, estimate_tokens
from hobees.core.tool_registry import get_skill_metadata
from hobees.db.models import Bee, Hive, LLMProvider, Run

DEFAULT_SUPERVISOR_PROMPT = """\
You are the Hive Supervisor for "{hive_name}". Your job is to accomplish the
user's goal by delegating work to the specialist Worker Bees in this Hive and
synthesizing their answers into a final reply.

Available workers:
{worker_roster}

Rules:
- Inspect each worker's role_description before assigning work.
- Delegate to ONE worker at a time; wait for their result before deciding next.
- When the goal is complete, give the final answer yourself. Do not ask the
  user to pick a worker.
- If a worker reports an error, decide whether to retry, re-route, or report
  failure.
"""


def _build_hive_graph(
    hive: Hive,
    bees: list[Bee],
    providers: dict[int, LLMProvider],
    db_url: str | URL,
    thread_id: str,
    run_id: int | None = None,
    session_override_thinking: str | None = None,  # v1.1: session-wide thinking override
    artifact_root: str | Path | None = None,
    approval_mode: str | None = None,
    container_name: str | None = None,
):
    """Build the shared Hive graph and return its run context."""
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_core.runnables.config import merge_configs
    from langchain_core.tools import StructuredTool
    from langgraph.graph import END, START, MessagesState, StateGraph
    from hobees.core.approval import (
        ApprovalMiddleware,
        resolve_approval_mode,
    )

    class RequestTransformMiddleware(AgentMiddleware):
        def __init__(
            self,
            transform: Callable[[ModelRequest], ModelRequest],
        ) -> None:
            self.transform = transform

        def wrap_model_call(
            self,
            request: ModelRequest,
            handler: Callable[[ModelRequest], ModelResponse],
        ) -> ModelResponse:
            return handler(self.transform(request))

        async def awrap_model_call(
            self,
            request: ModelRequest,
            handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        ) -> ModelResponse:
            return await handler(self.transform(request))

    # Build thread_id for this run
    from hobees.core.approval import resolve_container_name, resolve_thread_id
    container_name = resolve_container_name(container_name)
    if not thread_id:
        thread_id = resolve_thread_id("hive", hive.name, container_name=container_name)

    # Set thread context for tool truncation and project root (artifacts directory)
    from hobees.core.tool_registry import set_thread_context
    from hobees.config import settings
    from hobees.core.tracing import (
        HiveTraceCallbackHandler,
        HiveTraceEvent,
        emit_trace_event,
    )

    if artifact_root is not None:
        project_root = Path(artifact_root)
    elif hasattr(hive, "project_path") and hive.project_path:
        project_root = Path(hive.project_path)
    else:
        from hobees.core.paths import safe_path_component

        project_root = settings.artifacts_root / safe_path_component(hive.name)

    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "output").mkdir(parents=True, exist_ok=True)
    traces_dir = project_root / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    set_thread_context(thread_id, project_root=str(project_root.resolve()))

    # Get hive name for memory namespace
    hive_name = hive.name

    # Get global + hive memories for injection
    memory_namespaces = extract_namespaces(global_=True, hive_name=hive_name)
    memory_block = build_memory_block(memory_namespaces)

    # Get skill metadata for all skills (will be filtered per bee)
    all_skill_metadata = get_skill_metadata()

    def worker_prompt_middleware(prompt_fn):
        return RequestTransformMiddleware(
            lambda request: request.override(messages=prompt_fn(request.state))
        )

    def make_delegation_tool(worker_agent, worker, worker_trace_handler):
        normalized_name = re.sub(r"\s+", "_", worker.name.strip()).lower()

        def delegate_to_worker(description: str, config: RunnableConfig) -> str:
            started_at = time.monotonic()
            emit_trace_event(
                HiveTraceEvent(
                    thread_id=thread_id,
                    hive_name=hive.name,
                    run_id=run_id,
                    event_type="WORKER_START",
                    source="supervisor",
                    target=worker.name,
                    payload={"task_length": len(description)},
                ),
                traces_dir,
            )
            try:
                worker_config = merge_configs(
                    config,
                    {"callbacks": [worker_trace_handler]},
                )
                result = worker_agent.invoke(
                    {"messages": [HumanMessage(content=description)]},
                    config=worker_config,
                )
                for message in reversed(result.get("messages", [])):
                    if isinstance(message, AIMessage) and not message.tool_calls:
                        content = str(message.content)
                        emit_trace_event(
                            HiveTraceEvent(
                                thread_id=thread_id,
                                hive_name=hive.name,
                                run_id=run_id,
                                event_type="WORKER_END",
                                source=worker.name,
                                target="supervisor",
                                payload={
                                    "status": "completed",
                                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                                    "reply_length": len(content),
                                },
                            ),
                            traces_dir,
                        )
                        return content
                raise RuntimeError(f"Worker {worker.name!r} returned no final response")
            except Exception as exc:
                emit_trace_event(
                    HiveTraceEvent(
                        thread_id=thread_id,
                        hive_name=hive.name,
                        run_id=run_id,
                        event_type="WORKER_END",
                        source=worker.name,
                        target="supervisor",
                        payload={
                            "status": "failed",
                            "duration_ms": int((time.monotonic() - started_at) * 1000),
                            "error_type": type(exc).__name__,
                        },
                    ),
                    traces_dir,
                )
                raise

        return StructuredTool.from_function(
            func=delegate_to_worker,
            name=f"transfer_to_{normalized_name}",
            description=(
                f"Delegate a focused subtask to {worker.name}, whose role is "
                f"{worker.role_description}. Provide the task as a clear description."
            ),
        )

    delegation_tools = []
    for bee in bees:
        provider = providers[bee.provider_id]
        worker_trace_handler = HiveTraceCallbackHandler(
            hive_name=hive.name,
            thread_id=thread_id,
            run_id=run_id,
            agent_name=bee.name,
            traces_dir=traces_dir,
        )

        # Determine thinking level: session override > bee setting > default
        # "auto" means use the bee's configured level
        if session_override_thinking and session_override_thinking != "auto":
            thinking_level = session_override_thinking
        else:
            thinking_level = bee.thinking_level or "off"

        model = get_chat_model(
            provider,
            bee.model_name,
            bee.temperature,
            callbacks=[
                TelemetryCallbackHandler(
                    bee_name=bee.name,
                    provider_alias=provider.alias,
                    model_name=bee.model_name,
                    thread_id=thread_id,
                    container_name=container_name,
                    run_id=run_id,
                    rates={
                        provider.alias: (
                            float(provider.input_cost_per_1m),
                            float(provider.output_cost_per_1m),
                        )
                    },
                ),
            ],
            thinking_level=thinking_level,
        )

        # Get bee-specific skills
        bee_skills = [
            {
                "name": s["name"] if isinstance(s, dict) else s.name,
                "description": s["description"] if isinstance(s, dict) else s.description,
            }
            for s in all_skill_metadata
            if (s["name"] if isinstance(s, dict) else s.name) in [
                getattr(skill, "name", str(skill)) for skill in getattr(bee, "skills", [])
            ]
        ]

        # Get bee-specific memories
        bee_memory_namespaces = extract_namespaces(global_=True, hive_name=hive.name, bee_name=bee.name)
        bee_memories = get_memories_for_namespaces(bee_memory_namespaces)

        # Worker dynamic prompt using project_worker_context (Worker Context Isolation)
        def make_worker_prompt(state: dict, b=bee, b_skills=bee_skills, b_mems=bee_memories):
            from langchain_core.messages import ToolMessage
            msgs = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
            subtask = ""
            for m in reversed(msgs):
                tool_calls = getattr(m, "tool_calls", None) or []
                for tc in tool_calls:
                    if tc.get("name") in (f"transfer_to_{b.name}", b.name):
                        args = tc.get("args") or {}
                        subtask = args.get("description") or str(args)
                        break
                if subtask:
                    break
                content = getattr(m, "content", None)
                if getattr(m, "name", None) in ("supervisor", None) and content and not getattr(m, "tool_calls", None):
                    subtask = str(content)
                    break

            if not subtask and msgs:
                subtask = str(getattr(msgs[-1], "content", ""))

            # Keep active trailing tool messages for multi-step tool calls
            tail = []
            i = len(msgs) - 1
            while i >= 0:
                m = msgs[i]
                is_tool_msg = (
                    isinstance(m, ToolMessage)
                    and not (getattr(m, "name", "") or "").startswith("transfer_")
                )
                is_ai_call = (
                    isinstance(m, AIMessage)
                    and bool(getattr(m, "tool_calls", None))
                    and any(not tc.get("name", "").startswith("transfer_") for tc in m.tool_calls)
                )
                if is_tool_msg or is_ai_call:
                    tail.insert(0, m)
                    i -= 1
                else:
                    break

            projected = project_worker_context(
                bee_name=b.name,
                bee_role=b.role_description,
                bee_system_prompt=b.system_prompt or "",
                bee_skills=b_skills,
                memories=b_mems,
                running_summary=None,
                subtask=subtask or "Complete your assigned subtask.",
            )
            return [SystemMessage(content=projected)] + tail

        worker_agent = create_agent(
            model=model,
            tools=get_tools(bee.tool_names),
            middleware=[
                worker_prompt_middleware(make_worker_prompt),
                ApprovalMiddleware(
                    bee_name=bee.name,
                    hive_name=hive.name,
                    thread_id=thread_id,
                    container_name=container_name,
                    approval_mode=(
                        approval_mode
                        if approval_mode in {"interactive", "auto", "strict", "pause"}
                        else resolve_approval_mode(interactive=sys.stdin.isatty())
                    ),
                    require_approval=getattr(bee, "require_approval", None),
                ),
            ],
            name=bee.name,
        )
        delegation_tools.append(
            make_delegation_tool(worker_agent, bee, worker_trace_handler)
        )

    # Supervisor with thinking level
    supervisor_provider = providers[hive.supervisor_provider_id]
    # "auto" means use the hive's configured level
    if session_override_thinking and session_override_thinking != "auto":
        supervisor_thinking = session_override_thinking
    else:
        supervisor_thinking = hive.supervisor_thinking_level or "medium"

    supervisor_model = get_chat_model(
        supervisor_provider,
        hive.supervisor_model_name,
        0.0,
        callbacks=[
            TelemetryCallbackHandler(
                bee_name=f"{hive.name}_supervisor",
                provider_alias=supervisor_provider.alias,
                model_name=hive.supervisor_model_name,
                thread_id=thread_id,
                container_name=container_name,
                run_id=run_id,
                rates={
                    supervisor_provider.alias: (
                        float(supervisor_provider.input_cost_per_1m),
                        float(supervisor_provider.output_cost_per_1m),
                    )
                },
            ),
            HiveTraceCallbackHandler(
                hive_name=hive.name,
                thread_id=thread_id,
                run_id=run_id,
                agent_name="supervisor",
                traces_dir=traces_dir,
            ),
        ],
        thinking_level=supervisor_thinking,
    )

    roster = "\n".join(
        f"- {bee.name}: {bee.role_description}" for bee in bees
    )
    supervisor_prompt = (hive.supervisor_prompt or DEFAULT_SUPERVISOR_PROMPT).format(
        hive_name=hive.name, worker_roster=roster
    )
    if memory_block:
        supervisor_prompt = f"{supervisor_prompt}\n\n{memory_block}"

    # Supervisor rolling compaction and sequential delegation.
    def prepare_supervisor_request(request):
        messages = request.messages
        if messages:
            context_window = supervisor_provider.context_window_tokens or 128000
            kept, summary = compact_messages(
                messages=messages,
                context_window=context_window,
                summarizer_model=None,
            )
            if summary:
                if run_id:
                    try:
                        from hobees.db.session import session_scope
                        with session_scope() as session:
                            run_obj = session.get(Run, run_id)
                            if run_obj:
                                run_obj.compacted_count = (run_obj.compacted_count or 0) + 1
                    except Exception:
                        pass
                summary_msg = SystemMessage(content=f"## Compressed Earlier Context\n{summary}")
                messages = [summary_msg, *kept]

        model_settings = dict(request.model_settings or {})
        model_name = getattr(request.model, "model_name", None)
        if (
            "parallel_tool_calls" in inspect.signature(request.model.bind_tools).parameters
            and model_name not in {"o3-mini", "o3", "o4-mini"}
        ):
            model_settings["parallel_tool_calls"] = False

        return request.override(messages=messages, model_settings=model_settings)

    supervisor_agent = create_agent(
        model=supervisor_model,
        tools=delegation_tools,
        system_prompt=supervisor_prompt,
        middleware=[RequestTransformMiddleware(prepare_supervisor_request)],
        name="supervisor",
    )
    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", supervisor_agent)
    graph.add_edge(START, "supervisor")
    graph.add_edge("supervisor", END)

    # Rendered with the password intact: `str(db_url)` would write `***` and the
    # checkpointer would then try to authenticate with that, while SQLAlchemy - holding the
    # URL object - connects fine. See hobees.db.backends.render_db_url.
    from hobees.db.backends import render_db_url

    return graph, thread_id, project_root, traces_dir, render_db_url(db_url)


def _emit_hive_event(
    event_type: str,
    hive: Hive,
    thread_id: str,
    run_id: int | None,
    project_root: Path,
    traces_dir: Path,
    error: BaseException | None = None,
) -> None:
    from hobees.core.tracing import HiveTraceEvent, emit_trace_event

    payload = {"project_root": str(project_root.resolve())}
    if error is not None:
        payload["error"] = str(error)
    emit_trace_event(
        HiveTraceEvent(
            thread_id=thread_id,
            hive_name=hive.name,
            run_id=run_id,
            event_type=event_type,
            source="system",
            target="supervisor" if event_type == "HIVE_START" else "user",
            payload=payload,
        ),
        traces_dir,
    )


@contextmanager
def hive_app(
    hive: Hive,
    bees: list[Bee],
    providers: dict[int, LLMProvider],
    db_url: str | URL,
    thread_id: str,
    run_id: int | None = None,
    session_override_thinking: str | None = None,
    artifact_root: str | Path | None = None,
    approval_mode: str | None = None,
    container_name: str | None = None,
) -> Iterator[object]:
    """Yield a Hive graph with synchronous checkpoints."""
    from hobees.db.backends import get_database_backend, get_postgres_checkpoint_url

    backend = get_database_backend(db_url)
    graph, thread_id, project_root, traces_dir, db_url_str = _build_hive_graph(
        hive, bees, providers, db_url, thread_id, run_id,
        session_override_thinking, artifact_root, approval_mode, container_name,
    )

    _emit_hive_event("HIVE_START", hive, thread_id, run_id, project_root, traces_dir)
    try:
        if backend == "sqlite":
            from sqlalchemy.engine import make_url

            sqlite_path = make_url(db_url_str).database
            if not sqlite_path or sqlite_path == ":memory:":
                from langgraph.checkpoint.memory import MemorySaver

                yield graph.compile(checkpointer=MemorySaver())
            else:
                from langgraph.checkpoint.sqlite import SqliteSaver

                with SqliteSaver.from_conn_string(sqlite_path) as saver:
                    saver.setup()
                    yield graph.compile(checkpointer=saver)
        else:
            from langgraph.checkpoint.postgres import PostgresSaver

            conn_string = get_postgres_checkpoint_url(db_url_str)
            with PostgresSaver.from_conn_string(conn_string) as saver:
                yield graph.compile(checkpointer=saver)
    except BaseException as exc:
        _emit_hive_event(
            "HIVE_ERROR", hive, thread_id, run_id, project_root, traces_dir, exc
        )
        raise
    else:
        _emit_hive_event(
            "HIVE_COMPLETE", hive, thread_id, run_id, project_root, traces_dir
        )


@asynccontextmanager
async def hive_app_async(
    hive: Hive,
    bees: list[Bee],
    providers: dict[int, LLMProvider],
    db_url: str | URL,
    thread_id: str,
    run_id: int | None = None,
    session_override_thinking: str | None = None,
    artifact_root: str | Path | None = None,
    approval_mode: str | None = None,
    container_name: str | None = None,
):
    """Yield a Hive graph with asynchronous, persistent checkpoints."""
    from hobees.db.backends import get_database_backend, get_postgres_checkpoint_url

    backend = get_database_backend(db_url)
    graph, thread_id, project_root, traces_dir, db_url_str = _build_hive_graph(
        hive, bees, providers, db_url, thread_id, run_id,
        session_override_thinking, artifact_root, approval_mode, container_name,
    )

    _emit_hive_event("HIVE_START", hive, thread_id, run_id, project_root, traces_dir)
    try:
        if backend == "sqlite":
            from sqlalchemy.engine import make_url
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            sqlite_path = make_url(db_url_str).database or ":memory:"
            async with AsyncSqliteSaver.from_conn_string(sqlite_path) as saver:
                await saver.setup()
                yield graph.compile(checkpointer=saver)
        else:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            conn_string = get_postgres_checkpoint_url(db_url_str)
            async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
                await saver.setup()
                yield graph.compile(checkpointer=saver)
    except BaseException as exc:
        _emit_hive_event(
            "HIVE_ERROR", hive, thread_id, run_id, project_root, traces_dir, exc
        )
        raise
    else:
        _emit_hive_event(
            "HIVE_COMPLETE", hive, thread_id, run_id, project_root, traces_dir
        )


__all__ = ["hive_app", "hive_app_async", "DEFAULT_SUPERVISOR_PROMPT"]