"""Unit tests for Tracing Engine and EventBroker."""

import asyncio
import json
import threading
import pytest
from pathlib import Path
from langchain_core.outputs import LLMResult, ChatGeneration
from langchain_core.messages import AIMessage

from hobees.core.tracing import (
    HiveTraceEvent,
    EventBroker,
    HiveTraceCallbackHandler,
    emit_trace_event,
    write_run_manifest,
)
from hobees.config import settings


def test_event_broker():
    async def _run():
        broker = EventBroker.get_instance()
        q = broker.subscribe()

        event = HiveTraceEvent(
            thread_id="test_th_1",
            hive_name="test_hive",
            event_type="HIVE_START",
            source="system",
            target="supervisor",
            payload={"info": "started"},
        )
        broker.publish(event)

        received = await asyncio.wait_for(q.get(), timeout=1.0)
        assert received["thread_id"] == "test_th_1"
        assert received["event_type"] == "HIVE_START"

        broker.unsubscribe(q)

    asyncio.run(_run())


def test_event_broker_publishes_from_worker_thread():
    async def _run():
        broker = EventBroker()
        q = broker.subscribe()
        event = {
            "thread_id": "thread-from-worker",
            "event_type": "TOOL_START",
        }
        worker = threading.Thread(target=broker.publish, args=(event,))
        worker.start()
        worker.join()

        assert await asyncio.wait_for(q.get(), timeout=1.0) == event
        broker.unsubscribe(q)

    asyncio.run(_run())


def test_hive_trace_callback_handler(tmp_path):
    traces_dir = tmp_path / "traces"
    handler = HiveTraceCallbackHandler(
        hive_name="test_hive",
        thread_id="th_trace_1",
        run_id=1,
        agent_name="coder",
        traces_dir=traces_dir,
    )

    # Tool start
    handler.on_tool_start({"name": "write_file"}, "input text")
    # Tool end
    handler.on_tool_end("WROTE file.py (100 bytes)")

    trace_file = traces_dir / "th_trace_1.jsonl"
    assert trace_file.exists()
    lines = [json.loads(line) for line in trace_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["event_type"] == "TOOL_START"
    assert lines[0]["target"] == "write_file"
    assert lines[1]["event_type"] == "TOOL_END"


def test_hive_trace_omits_thought_and_sanitizes_sensitive_data(tmp_path):
    handler = HiveTraceCallbackHandler(
        hive_name="test_hive",
        thread_id="th_trace_error",
        agent_name="coder",
        traces_dir=tmp_path / "traces",
    )
    run_id = "tool-run"
    secret = "sk-test-super-secret-token123"
    response = LLMResult(
        generations=[
            [
                ChatGeneration(
                    message=AIMessage(
                        content=f"answer api_key={secret}",
                        additional_kwargs={"reasoning_content": "private reasoning"},
                    )
                )
            ]
        ]
    )

    handler.on_llm_end(response)
    handler.on_tool_start(
        {"name": "write_file"},
        f"content={secret}",
        run_id=run_id,
        inputs={"path": "output.txt", "content": secret, "api_key": secret},
    )
    handler.on_tool_end(f"wrote {secret}", run_id=run_id)
    handler.on_tool_error(RuntimeError(f"tool failed token={secret}"))
    handler.on_llm_error(RuntimeError(f"model failed token={secret}"))

    events = [
        json.loads(line)
        for line in (tmp_path / "traces" / "th_trace_error.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    events_by_type = {event["event_type"]: event for event in events}
    assert "THOUGHT" not in events_by_type
    assert {"BEE_REPLY", "TOOL_START", "TOOL_END", "HIVE_ERROR"} <= events_by_type.keys()
    assert events_by_type["BEE_REPLY"]["payload"]["content_preview"] == "answer api_key=[REDACTED]"
    tool_start = next(event for event in events if event["event_type"] == "TOOL_START")
    tool_end = next(
        event
        for event in events
        if event["event_type"] == "TOOL_END" and event["payload"].get("failed") is False
    )
    assert tool_start["payload"]["argument_names"] == ["api_key", "content", "path"]
    assert "content" not in tool_end["payload"]
    assert "output_preview" not in tool_end["payload"]
    assert all(secret not in json.dumps(event) for event in events)
    assert events[-1]["payload"]["error_type"] == "RuntimeError"
    assert events[-1]["payload"]["error_preview"] == "model failed token=[REDACTED]"


def test_trace_content_metadata_mode_omits_message_previews(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "trace_content_mode", "metadata")
    handler = HiveTraceCallbackHandler(
        hive_name="test_hive",
        thread_id="th_metadata",
        agent_name="worker",
        traces_dir=tmp_path / "traces",
    )
    response = LLMResult(
        generations=[
            [ChatGeneration(message=AIMessage(content="private response"))]
        ]
    )

    handler.on_llm_end(response)

    event = json.loads(
        (tmp_path / "traces" / "th_metadata.jsonl").read_text().splitlines()[0]
    )
    assert event["event_type"] == "BEE_REPLY"
    assert event["payload"] == {"content_length": len("private response")}


def test_emit_trace_event_sanitizes_persisted_and_live_payloads(tmp_path):
    async def _run():
        broker = EventBroker.get_instance()
        queue = broker.subscribe()
        secret = "sk-test-super-secret-token123"
        event = HiveTraceEvent(
            thread_id="trace_redaction",
            hive_name="test_hive",
            event_type="HIVE_ERROR",
            source="system",
            payload={
                "details": f"token={secret}",
                "header": f"Authorization: Bearer {secret}",
                "credentials": {"password": secret},
                "reasoning_content": "private reasoning",
            },
        )
        try:
            emit_trace_event(event, tmp_path / "traces")
            live = await asyncio.wait_for(queue.get(), timeout=1.0)
        finally:
            broker.unsubscribe(queue)

        persisted = json.loads(
            (tmp_path / "traces" / "trace_redaction.jsonl").read_text().splitlines()[0]
        )
        assert live == persisted
        assert secret not in json.dumps(live)
        assert live["payload"]["credentials"] == "[REDACTED]"
        assert live["payload"]["details"] == "token=[REDACTED]"
        assert live["payload"]["header"] == "Authorization: [REDACTED]"
        assert "reasoning_content" not in live["payload"]

    asyncio.run(_run())


def test_write_run_manifest(tmp_path):
    manifest_data = {
        "run_id": 1,
        "thread_id": "th_man_1",
        "hive_name": "test_hive",
        "goal": "Build feature",
        "status": "completed",
    }
    path = write_run_manifest(tmp_path, manifest_data)
    assert path.exists()

    content = json.loads(path.read_text())
    assert content["hive_name"] == "test_hive"
    assert content["last_run"]["status"] == "completed"
    assert len(content["runs"]) == 1
