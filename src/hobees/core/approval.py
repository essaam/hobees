"""Human-in-the-loop approval policy and LangGraph tool middleware."""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import interrupt

ApprovalMode = Literal["interactive", "auto", "strict", "pause"]
ApprovalAction = Literal["approve", "edit", "reject"]

#: The levels a session or global setting may be set to. Kept here so the core
#: resolver and every front-end share one definition.
APPROVAL_MODES: tuple[str, ...] = ("interactive", "auto", "strict", "pause")


def resolve_container_name(cli_container: str | None = None) -> str:
    return (
        cli_container
        or os.getenv("HOBEES_CONTAINER_NAME")
        or os.getenv("HOSTNAME")
        or socket.gethostname()
        or "local"
    )


def resolve_thread_id(
    scope: Literal["hive", "bee", "assistant"],
    entity_name: str | None = None,
    user_thread: str | None = None,
    container_name: str | None = None,
) -> str:
    container = resolve_container_name(container_name)
    entity = entity_name or "default"
    if user_thread:
        parts = user_thread.split(":", 3)
        if len(parts) == 4 and parts[1] in {"hive", "bee", "assistant"}:
            return user_thread
        return f"{container}:{scope}:{entity}:{user_thread}"
    return f"{container}:{scope}:{entity}:{uuid.uuid4().hex[:8]}"


def resolve_approval_mode(
    cli_mode: ApprovalMode | None = None,
    *,
    session_mode: ApprovalMode | None = None,
    interactive: bool | None = None,
) -> ApprovalMode:
    """Resolve the effective level.

    Precedence (specs/HITL.md §2.3): CLI flag → session override → environment /
    saved global setting → context default. Unknown values are ignored rather
    than trusted, so a bad setting can never widen a policy.
    """
    for candidate in (cli_mode, session_mode):
        if candidate in APPROVAL_MODES:
            return candidate  # type: ignore[return-value]
    env_mode = os.getenv("HOBEES_APPROVAL_MODE")
    if env_mode in APPROVAL_MODES:
        return env_mode  # type: ignore[return-value]
    from hobees.config import settings

    if settings.approval_mode in APPROVAL_MODES:
        return settings.approval_mode  # type: ignore[return-value]
    if interactive is None:
        interactive = sys.stdin.isatty()
    return "interactive" if interactive else "strict"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def record_approval_event(
    *,
    container_name: str,
    thread_id: str,
    hive_name: str | None,
    bee_name: str,
    tool_name: str,
    tool_call_id: str,
    approval_mode: ApprovalMode,
    decision: Literal["pending", "approve", "edit", "reject"],
    original_args: dict[str, Any] | None = None,
    final_args: dict[str, Any] | None = None,
    reason: str | None = None,
    checkpoint_id: str | None = None,
    requested_at: datetime | None = None,
) -> int | None:
    from hobees.db.session import session_scope
    from hobees.db.models import ApprovalEvent

    requested_at = requested_at or _utc_now()
    resolved_at = None if decision == "pending" else _utc_now()
    try:
        with session_scope() as session:
            event = ApprovalEvent(
                container_name=container_name,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                hive_name=hive_name,
                bee_name=bee_name,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                approval_mode=approval_mode,
                decision=decision,
                original_args_json=json.dumps(original_args or {}, sort_keys=True),
                final_args_json=json.dumps(final_args, sort_keys=True) if final_args is not None else None,
                reason=reason,
                requested_at=requested_at,
                resolved_at=resolved_at,
            )
            session.add(event)
            session.flush()
            return event.id
    except Exception:
        # Approval safety must not be weakened by a telemetry-store failure.
        return None


class ApprovalMiddleware(AgentMiddleware):
    def __init__(
        self,
        *,
        bee_name: str,
        hive_name: str,
        thread_id: str,
        container_name: str,
        approval_mode: ApprovalMode,
        require_approval: list[str] | None,
    ) -> None:
        super().__init__()
        self.bee_name = bee_name
        self.hive_name = hive_name
        self.thread_id = thread_id
        self.container_name = container_name
        self.approval_mode = approval_mode
        self.require_approval = set(require_approval or [])

    def _handle(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        tool_call = request.tool_call
        tool_name = str(tool_call.get("name", ""))
        if tool_name not in self.require_approval:
            return handler(request)

        tool_args = tool_call.get("args") or {}
        tool_call_id = str(tool_call.get("id") or "")
        requested_at = _utc_now()

        if self.approval_mode == "auto":
            record_approval_event(
                container_name=self.container_name,
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                bee_name=self.bee_name,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                approval_mode="auto",
                decision="approve",
                original_args=tool_args,
                final_args=tool_args,
                requested_at=requested_at,
            )
            return handler(request)

        if self.approval_mode == "strict":
            record_approval_event(
                container_name=self.container_name,
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                bee_name=self.bee_name,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                approval_mode="strict",
                decision="reject",
                reason="Blocked by strict approval policy",
                original_args=tool_args,
                requested_at=requested_at,
            )
            return ToolMessage(
                tool_call_id=tool_call_id,
                content=f"Action rejected by policy: '{tool_name}' is not permitted in strict mode.",
            )

        record_approval_event(
            container_name=self.container_name,
            thread_id=self.thread_id,
            hive_name=self.hive_name,
            bee_name=self.bee_name,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            approval_mode=self.approval_mode,
            decision="pending",
            original_args=tool_args,
            requested_at=requested_at,
        )
        decision = interrupt(
            {
                "type": "tool_approval_request",
                "container_name": self.container_name,
                "thread": self.thread_id,
                "bee": self.bee_name,
                "tool": tool_name,
                "tool_call_id": tool_call_id,
                "args": tool_args,
                "requested_at": requested_at.isoformat(),
            }
        )
        action = decision.get("action", "approve")

        if action == "reject":
            reason = decision.get("reason", "Rejected by operator.")
            record_approval_event(
                container_name=self.container_name,
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                bee_name=self.bee_name,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                approval_mode=self.approval_mode,
                decision="reject",
                reason=reason,
                original_args=tool_args,
                requested_at=requested_at,
            )
            return ToolMessage(
                tool_call_id=tool_call_id,
                content=f"Action rejected by user: '{tool_name}' was denied. Reason: {reason}",
            )

        if action == "edit":
            modified_args = decision["args"]
            record_approval_event(
                container_name=self.container_name,
                thread_id=self.thread_id,
                hive_name=self.hive_name,
                bee_name=self.bee_name,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                approval_mode=self.approval_mode,
                decision="edit",
                original_args=tool_args,
                final_args=modified_args,
                requested_at=requested_at,
            )
            edited_request = request.override(
                tool_call={**tool_call, "args": modified_args}
            )
            result = handler(edited_request)
            if isinstance(result, ToolMessage):
                result.content = (
                    f"[Note: Operator modified tool arguments to {modified_args} before approving]\n"
                    f"{result.content}"
                )
            return result

        record_approval_event(
            container_name=self.container_name,
            thread_id=self.thread_id,
            hive_name=self.hive_name,
            bee_name=self.bee_name,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            approval_mode=self.approval_mode,
            decision="approve",
            original_args=tool_args,
            final_args=tool_args,
            requested_at=requested_at,
        )
        return handler(request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        return self._handle(request, handler)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        tool_call = request.tool_call
        tool_name = str(tool_call.get("name", ""))
        if tool_name not in self.require_approval:
            return await handler(request)
        tool_args = tool_call.get("args") or {}
        tool_call_id = str(tool_call.get("id") or "")
        requested_at = _utc_now()

        if self.approval_mode == "auto":
            record_approval_event(
                container_name=self.container_name, thread_id=self.thread_id,
                hive_name=self.hive_name, bee_name=self.bee_name,
                tool_name=tool_name, tool_call_id=tool_call_id,
                approval_mode="auto", decision="approve",
                original_args=tool_args, final_args=tool_args,
                requested_at=requested_at,
            )
            return await handler(request)

        if self.approval_mode == "strict":
            record_approval_event(
                container_name=self.container_name, thread_id=self.thread_id,
                hive_name=self.hive_name, bee_name=self.bee_name,
                tool_name=tool_name, tool_call_id=tool_call_id,
                approval_mode="strict", decision="reject",
                reason="Blocked by strict approval policy",
                original_args=tool_args, requested_at=requested_at,
            )
            return ToolMessage(
                tool_call_id=tool_call_id,
                content=f"Action rejected by policy: '{tool_name}' is not permitted in strict mode.",
            )

        record_approval_event(
            container_name=self.container_name, thread_id=self.thread_id,
            hive_name=self.hive_name, bee_name=self.bee_name,
            tool_name=tool_name, tool_call_id=tool_call_id,
            approval_mode=self.approval_mode, decision="pending",
            original_args=tool_args, requested_at=requested_at,
        )
        decision = interrupt({
            "type": "tool_approval_request",
            "container_name": self.container_name,
            "thread": self.thread_id,
            "bee": self.bee_name,
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "args": tool_args,
            "requested_at": requested_at.isoformat(),
        })
        action = decision.get("action", "approve")
        if action == "reject":
            reason = decision.get("reason", "Rejected by operator.")
            record_approval_event(
                container_name=self.container_name, thread_id=self.thread_id,
                hive_name=self.hive_name, bee_name=self.bee_name,
                tool_name=tool_name, tool_call_id=tool_call_id,
                approval_mode=self.approval_mode, decision="reject",
                reason=reason, original_args=tool_args, requested_at=requested_at,
            )
            return ToolMessage(
                tool_call_id=tool_call_id,
                content=f"Action rejected by user: '{tool_name}' was denied. Reason: {reason}",
            )
        if action == "edit":
            modified_args = decision["args"]
            record_approval_event(
                container_name=self.container_name, thread_id=self.thread_id,
                hive_name=self.hive_name, bee_name=self.bee_name,
                tool_name=tool_name, tool_call_id=tool_call_id,
                approval_mode=self.approval_mode, decision="edit",
                original_args=tool_args, final_args=modified_args,
                requested_at=requested_at,
            )
            result = await handler(request.override(
                tool_call={**tool_call, "args": modified_args}
            ))
            if isinstance(result, ToolMessage):
                result.content = (
                    f"[Note: Operator modified tool arguments to {modified_args} before approving]\n"
                    f"{result.content}"
                )
            return result
        record_approval_event(
            container_name=self.container_name, thread_id=self.thread_id,
            hive_name=self.hive_name, bee_name=self.bee_name,
            tool_name=tool_name, tool_call_id=tool_call_id,
            approval_mode=self.approval_mode, decision="approve",
            original_args=tool_args, final_args=tool_args,
            requested_at=requested_at,
        )
        return await handler(request)
