"""Tests for the hobees Web UI backend (`hobees.web.app`) and bundled static SPA."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hobees.config import settings
from hobees.core.tracing import trace_filename
from hobees.db.models import ApprovalEvent, Base, Bee, LLMProvider, Run, UsageEvent
from hobees.db.session import dispose_engine, get_engine, session_scope
from hobees.web.app import create_web_app


@pytest.fixture()
def web_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "web_test.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(settings, "artifacts_root", artifacts_dir)
    dispose_engine()
    engine = get_engine()
    Base.metadata.create_all(engine)

    yield tmp_path, artifacts_dir

    dispose_engine()


def test_static_assets_and_spa_routing(web_env):
    client = TestClient(create_web_app())

    # Root serves SPA index.html
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    html = res.text

    # Every <script src="/assets/..."> and <link href="/assets/..."> must resolve with proper MIME
    js_paths = re.findall(r'src="(/assets/[^"]+\.js)"', html)
    css_paths = re.findall(r'href="(/assets/[^"]+\.css)"', html)
    assert js_paths, "Expected at least one built JS module in index.html"
    assert css_paths, "Expected at least one built CSS bundle in index.html"

    for js_path in js_paths:
        js_res = client.get(js_path)
        assert js_res.status_code == 200, f"{js_path} failed"
        assert "javascript" in js_res.headers["content-type"], (
            f"Expected javascript MIME for {js_path}, got {js_res.headers['content-type']}"
        )

    for css_path in css_paths:
        css_res = client.get(css_path)
        assert css_res.status_code == 200, f"{css_path} failed"
        assert "text/css" in css_res.headers["content-type"]

    fav = client.get("/favicon.svg")
    assert fav.status_code == 200
    assert "svg" in fav.headers["content-type"]

    # Missing asset must return 404, NEVER text/html
    missing_js = client.get("/assets/does-not-exist.js")
    assert missing_js.status_code == 404
    assert "text/html" not in missing_js.headers.get("content-type", "")

    # Deep SPA routes return index.html
    for spa_route in ["/traces", "/studio", "/storage", "/traces/worker-1:hive:dev:abc"]:
        spa = client.get(spa_route)
        assert spa.status_code == 200
        assert "text/html" in spa.headers["content-type"]


def test_status_and_tools_endpoints(web_env):
    client = TestClient(create_web_app())

    status = client.get("/api/v1/status")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"
    assert body["read_only"] is False

    tools = client.get("/api/v1/tools")
    assert tools.status_code == 200
    tool_names = {t["name"] for t in tools.json()["tools"]}
    assert {"read_file", "write_file", "list_directory", "run_python_calc"} <= tool_names


def test_read_only_guard_middleware(web_env):
    client = TestClient(create_web_app(read_only=True))

    assert client.get("/api/v1/status").json()["read_only"] is True
    assert client.get("/api/v1/providers").status_code == 200

    blocked = client.post(
        "/api/v1/providers",
        json={"alias": "blocked", "provider_type": "openai", "api_key_env": "OPENAI_API_KEY"},
    )
    assert blocked.status_code == 403


def test_studio_crud_and_yaml_roundtrip(web_env):
    client = TestClient(create_web_app())

    # Create provider
    p_res = client.post(
        "/api/v1/providers",
        json={
            "alias": "local-dev",
            "provider_type": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "api_key_env": "NONE",
            "default_model": "llama3",
            "input_cost_per_1m": 0.0,
            "output_cost_per_1m": 0.0,
            "context_window_tokens": 32000,
        },
    )
    assert p_res.status_code == 200
    provider = p_res.json()
    assert provider["api_key_env"] == "NONE"

    # Create bee with require_approval
    b_res = client.post(
        "/api/v1/bees",
        json={
            "name": "coder",
            "role_description": "Writes code",
            "system_prompt": "Be concise",
            "provider_id": provider["id"],
            "model_name": "llama3",
            "temperature": 0.1,
            "thinking_level": "low",
            "tool_names": ["read_file", "write_file"],
            "require_approval": ["write_file"],
        },
    )
    assert b_res.status_code == 200
    bee = b_res.json()
    assert bee["require_approval"] == ["write_file"]

    # Create hive
    h_res = client.post(
        "/api/v1/hives",
        json={
            "name": "dev-team",
            "goal_description": "Build software",
            "supervisor_provider_id": provider["id"],
            "supervisor_model_name": "llama3",
            "supervisor_thinking_level": "medium",
            "is_dynamic": False,
            "bee_ids": [bee["id"]],
        },
    )
    assert h_res.status_code == 200
    assert h_res.json()["bee_names"] == ["coder"]

    # Export YAML -> Import YAML round-trip (Windows-safe temp file + import_cmd schema)
    yaml_res = client.get("/api/v1/config/yaml")
    assert yaml_res.status_code == 200
    yaml_text = yaml_res.json()["yaml"]
    assert "provider_type: openai_compatible" in yaml_text
    assert "role_description: Writes code" in yaml_text
    assert "supervisor_thinking_level: medium" in yaml_text

    imp_res = client.post(
        "/api/v1/config/yaml",
        content=yaml_text,
        headers={"Content-Type": "text/plain"},
    )
    assert imp_res.status_code == 200
    assert imp_res.json()["success"] is True


def test_provider_model_detection_caches_models_on_the_row(web_env, monkeypatch):
    monkeypatch.setattr(
        "hobees.core.model_discovery.fetch_provider_models",
        lambda provider_row, refresh_cache=False: ["b-model", "a-model"],
    )
    client = TestClient(create_web_app())

    client.post(
        "/api/v1/providers",
        json={
            "alias": "detected-local",
            "provider_type": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "api_key_env": "NONE",
            "input_cost_per_1m": 0.0,
            "output_cost_per_1m": 0.0,
            "context_window_tokens": 32000,
        },
    )

    res = client.get("/api/v1/providers/models?alias=detected-local&refresh=true")
    assert res.status_code == 200
    body = res.json()
    assert body["alias"] == "detected-local"
    assert body["models"] == ["b-model", "a-model"]
    assert body["persisted"] is True

    row = [p for p in client.get("/api/v1/providers").json() if p["alias"] == "detected-local"][0]
    assert row["available_models"] == ["b-model", "a-model"]

    # An unsaved form can be probed too, without touching the database.
    inline = client.get(
        "/api/v1/providers/models?provider_type=openai_compatible&api_key_env=NONE"
    ).json()
    assert inline["alias"] is None
    assert inline["persisted"] is False

    # Read-only mode reports models but never writes them.
    read_only = TestClient(create_web_app(read_only=True))
    ro = read_only.get("/api/v1/providers/models?provider_type=openai_compatible&api_key_env=NONE").json()
    assert ro["models"] == ["b-model", "a-model"]
    assert ro["persisted"] is False


def test_provider_model_test_endpoint_reports_reasons_inline(web_env, monkeypatch):
    monkeypatch.delenv("HOBEES_TEST_MISSING_KEY", raising=False)

    class FakeChat:
        async def ainvoke(self, prompt: str):
            return SimpleNamespace(content="OK")

    monkeypatch.setattr("hobees.core.llm_factory.get_chat_model", lambda *args, **kwargs: FakeChat())

    client = TestClient(create_web_app())

    def make_provider(alias: str, api_key_env: str, default_model: str | None) -> dict:
        return client.post(
            "/api/v1/providers",
            json={
                "alias": alias,
                "provider_type": "openai_compatible",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": api_key_env,
                "default_model": default_model,
                "input_cost_per_1m": 0.0,
                "output_cost_per_1m": 0.0,
                "context_window_tokens": 32000,
            },
        ).json()

    make_provider("test-ok", "NONE", None)
    ok = client.post(
        "/api/v1/providers/test",
        json={"alias": "test-ok", "provider_type": "openai_compatible", "api_key_env": "NONE", "model": "a-model"},
    )
    assert ok.status_code == 200
    assert ok.json()["success"] is True
    assert ok.json()["model"] == "a-model"
    assert "OK" in ok.json()["detail"]

    make_provider("test-key", "HOBEES_TEST_MISSING_KEY", "z-model")
    missing_key = client.post(
        "/api/v1/providers/test",
        json={"alias": "test-key", "provider_type": "openai_compatible", "api_key_env": "HOBEES_TEST_MISSING_KEY"},
    ).json()
    assert missing_key["success"] is False
    assert "not set" in missing_key["detail"]

    no_model = client.post(
        "/api/v1/providers/test",
        json={"alias": "test-ok", "provider_type": "openai_compatible", "api_key_env": "NONE"},
    ).json()
    assert no_model["success"] is False
    assert "No model selected" in no_model["detail"]

    assert client.post("/api/v1/providers/test", json={"provider_type": "gemini", "model": "x"}).status_code == 400

    # The read-only guard blocks the POST test (mutating call).
    read_only = TestClient(create_web_app(read_only=True))
    assert read_only.post(
        "/api/v1/providers/test",
        json={"provider_type": "openai", "model": "x"},
    ).status_code == 403

    # Provider types are validated on create as well.
    assert client.post(
        "/api/v1/providers",
        json={"alias": "bad-type", "provider_type": "gemini", "api_key_env": "NONE"},
    ).status_code == 400


def test_assistant_chat_requires_a_model_and_stores_the_selection(web_env, monkeypatch):
    async def no_op_task(**kwargs):
        return None

    monkeypatch.setattr("hobees.web.app._run_single_bee_task", no_op_task)

    client = TestClient(create_web_app())
    provider = client.post(
        "/api/v1/providers",
        json={
            "alias": "assistant-no-default",
            "provider_type": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "api_key_env": "NONE",
            "input_cost_per_1m": 0.0,
            "output_cost_per_1m": 0.0,
            "context_window_tokens": 32000,
        },
    ).json()

    missing = client.post(
        "/api/v1/runs",
        json={"scope": "assistant", "entity_name": "default", "prompt": "hello", "provider_id": provider["id"]},
    )
    assert missing.status_code == 400
    assert "Pick a model" in missing.json()["detail"]

    accepted = client.post(
        "/api/v1/runs",
        json={
            "scope": "assistant",
            "entity_name": "default",
            "prompt": "hello",
            "provider_id": provider["id"],
            "model": "picked-model",
        },
    )
    assert accepted.status_code == 200

    with session_scope() as session:
        assistant = session.query(Bee).filter_by(name="assistant").first()
        assert assistant is not None
        assert assistant.provider_id == provider["id"]
        assert assistant.model_name == "picked-model"


def test_trace_reconstruction_and_approval_resolution(web_env):
    _, artifacts_dir = web_env
    client = TestClient(create_web_app())

    thread_id = "worker-1:hive:dev-team:abc12345"
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        run = Run(
            thread_id=thread_id,
            container_name="worker-1",
            mode="hive",
            goal="Write release notes",
            status="awaiting_approval",
            artifacts_dir=str(artifacts_dir / "dev-team"),
            started_at=now,
        )
        session.add(run)
        session.flush()
        session.add(
            UsageEvent(
                run_id=run.id,
                thread_id=thread_id,
                container_name="worker-1",
                bee_name="coder",
                provider_alias="local-dev",
                model_name="llama3",
                input_tokens=400,
                output_tokens=150,
                latency_ms=820,
            )
        )
        approval = ApprovalEvent(
            container_name="worker-1",
            thread_id=thread_id,
            hive_name="dev-team",
            bee_name="coder",
            tool_name="write_file",
            tool_call_id="call_01",
            approval_mode="pause",
            decision="pending",
            original_args_json=json.dumps({"path": "notes.md", "content": "v1"}),
            requested_at=now,
        )
        session.add(approval)
        session.flush()
        approval_id = approval.id

    # Write colon-escaped JSONL trace file
    traces_dir = artifacts_dir / "dev-team" / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    trace_file = traces_dir / trace_filename(thread_id)
    trace_file.write_text(
        "\n".join([
            json.dumps({
                "timestamp": now.isoformat(),
                "thread_id": thread_id,
                "hive_name": "dev-team",
                "event_type": "DELEGATE",
                "source": "supervisor",
                "target": "coder",
                "payload": {"subtask_preview": "Draft release notes"},
            }),
            json.dumps({
                "timestamp": now.isoformat(),
                "thread_id": thread_id,
                "hive_name": "dev-team",
                "event_type": "TOOL_START",
                "source": "coder",
                "target": "write_file",
                "payload": {"tool_name": "write_file", "argument_names": ["content", "path"], "argument_count": 2},
            }),
        ]) + "\n",
        encoding="utf-8",
    )

    # List traces filtered by container
    list_res = client.get("/api/v1/traces?container=worker-1")
    assert list_res.status_code == 200
    rows = list_res.json()
    assert len(rows) == 1
    assert rows[0]["total_tokens"] == 550
    assert rows[0]["pending_approvals"] == 1
    assert rows[0]["status"] == "awaiting_approval"

    # Detail trace merges JSONL + usage + pending approval
    detail_res = client.get(f"/api/v1/traces/{thread_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["total_tokens"] == 550
    assert len(detail["nodes"]) == 2
    assert detail["nodes"][1]["status"] == "awaiting_approval"
    assert detail["nodes"][1]["approval_info"][0]["id"] == approval_id

    # Edit & resolve approval updates existing row cleanly (no TypeError, clears pending queue)
    resolve_res = client.post(
        f"/api/v1/approvals/{approval_id}/resolve",
        json={"action": "edit", "args": {"path": "notes.md", "content": "v2 edited"}},
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["success"] is True

    pending_after = client.get("/api/v1/approvals?status=pending")
    assert pending_after.status_code == 200
    assert pending_after.json()["approvals"] == []


def test_memory_and_artifacts_endpoints(web_env):
    _, artifacts_dir = web_env
    client = TestClient(create_web_app())

    # Memory upsert + filter + delete
    assert client.post(
        "/api/v1/memories",
        json={"namespace": "global", "key": "style", "content": "Prefer concise code"},
    ).status_code == 200
    assert client.post(
        "/api/v1/memories",
        json={"namespace": "hive:dev-team", "key": "stack", "content": "FastAPI + React"},
    ).status_code == 200

    global_only = client.get("/api/v1/memories?namespace=global").json()
    assert [m["key"] for m in global_only["memories"]] == ["style"]

    hive_prefix = client.get("/api/v1/memories?namespace=hive:").json()
    assert [m["key"] for m in hive_prefix["memories"]] == ["stack"]

    # Artifacts listing + content + path traversal guard
    out_file = artifacts_dir / "dev-team" / "output" / "report.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("# Report\nAll good.", encoding="utf-8")

    art_list = client.get("/api/v1/artifacts?hive=dev-team").json()
    assert len(art_list["artifacts"]) == 1
    assert art_list["artifacts"][0]["name"] == "report.md"

    art_content = client.get("/api/v1/artifacts/content?hive=dev-team&path=report.md")
    assert art_content.status_code == 200
    assert "All good." in art_content.text

    traversal = client.get("/api/v1/artifacts/content?hive=dev-team&path=../../web_test.db")
    assert traversal.status_code == 403
