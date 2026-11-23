from types import SimpleNamespace

from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolMessage

from hobees.core.approval import (
    ApprovalMiddleware,
    resolve_approval_mode,
    resolve_thread_id,
)
from hobees.core.tracing import trace_filename


def test_resolve_thread_id_namespaces_and_preserves_full_key(monkeypatch):
    monkeypatch.setenv("HOBEES_CONTAINER_NAME", "worker-1")
    assert resolve_thread_id("hive", "dev-team", "pr-42") == (
        "worker-1:hive:dev-team:pr-42"
    )
    assert resolve_thread_id(
        "hive",
        "dev-team",
        "worker-1:hive:dev-team:pr-42",
    ) == "worker-1:hive:dev-team:pr-42"


def test_resolve_approval_mode_precedence(monkeypatch):
    monkeypatch.setenv("HOBEES_APPROVAL_MODE", "pause")
    assert resolve_approval_mode("strict") == "strict"
    assert resolve_approval_mode() == "pause"
    monkeypatch.delenv("HOBEES_APPROVAL_MODE")
    assert resolve_approval_mode(interactive=True) == "interactive"
    assert resolve_approval_mode(interactive=False) == "strict"


def test_strict_approval_returns_tool_message_without_execution(monkeypatch):
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return ToolMessage(tool_call_id="call-1", content="executed")

    monkeypatch.setattr(
        "hobees.core.approval.record_approval_event",
        lambda **_kwargs: None,
    )
    middleware = ApprovalMiddleware(
        bee_name="coder",
        hive_name="dev-team",
        thread_id="worker-1:hive:dev-team:pr-42",
        container_name="worker-1",
        approval_mode="strict",
        require_approval=["run_shell"],
    )
    request = SimpleNamespace(
        tool_call={"name": "run_shell", "args": {"command": "rm -rf tmp"}, "id": "call-1"}
    )
    result = middleware._handle(request, handler)

    assert not called
    assert isinstance(result, ToolMessage)
    assert "rejected by policy" in result.content


def test_auto_approval_executes(monkeypatch):
    monkeypatch.setattr(
        "hobees.core.approval.record_approval_event",
        lambda **_kwargs: None,
    )
    middleware = ApprovalMiddleware(
        bee_name="coder",
        hive_name="dev-team",
        thread_id="worker-1:hive:dev-team:pr-42",
        container_name="worker-1",
        approval_mode="auto",
        require_approval=["write_file"],
    )
    request = SimpleNamespace(
        tool_call={"name": "write_file", "args": {"path": "x"}, "id": "call-2"}
    )
    result = middleware._handle(
        request,
        lambda _request: ToolMessage(tool_call_id="call-2", content="executed"),
    )
    assert isinstance(result, ToolMessage)
    assert result.content == "executed"


def test_trace_filename_is_windows_safe():
    name = trace_filename("worker-1:hive:dev-team:pr-42")
    assert ":" not in name
    assert name == "worker-1__hive__dev-team__pr-42.jsonl"
