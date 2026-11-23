"""Tests for the hobees Web UI backend (`hobees.web.app`) and bundled static SPA."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hobees.config import settings
from hobees.core.tracing import trace_filename
from hobees.db.models import ApprovalEvent, Base, Run, UsageEvent
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
