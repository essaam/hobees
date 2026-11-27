"""Tests for the hobees Web UI backend (`hobees.web.app`) and bundled static SPA."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hobees import config
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


def test_container_plan_and_files_endpoints(web_env, monkeypatch):
    tmp_path, artifacts = web_env
    monkeypatch.setenv("HOBEES_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("hobees.core.container_prep.shutil.which", lambda _name: None)

    client = TestClient(create_web_app())

    with session_scope() as session:
        session.add(
            LLMProvider(
                alias="container-provider",
                provider_type="openai",
                base_url=None,
                api_key_env="OPENAI_API_KEY",
                default_model="m",
                input_cost_per_1m=0.0,
                output_cost_per_1m=0.0,
            )
        )
        session.commit()

    plan = client.get("/api/v1/containers/plan").json()
    assert "services:" in plan["compose"]
    assert "${OPENAI_API_KEY}" in plan["compose"]
    assert plan["docker_available"] is False
    assert plan["project_dir"] == str(tmp_path)
    assert plan["compose_exists"] is False

    custom = client.post(
        "/api/v1/containers/plan",
        json={"service": "worker", "profiles": ["dev"], "include_db": False},
    )
    assert custom.status_code == 200
    body = custom.json()
    assert "worker" in body["compose"]
    assert "postgres" not in body["compose"]

    bad = client.post("/api/v1/containers/plan", json={"service": "Bad Service"})
    assert any("valid compose service key" in warning for warning in bad.json()["warnings"])

    saved = client.post(
        "/api/v1/containers/files",
        json={
            "compose": "services:\n  app:\n    build: .\n    environment:\n      OPENAI_API_KEY: sk-live\n",
            "dockerfile": "FROM python:3.12-slim\nUSER hobees\n",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["success"] is True
    assert (tmp_path / "compose.yaml").is_file()
    assert (tmp_path / "Dockerfile").is_file()
    assert any("literal value" in warning for warning in saved.json()["warnings"])


    # Files must land inside the project root, whatever the request claims.
    outside = client.post(
        "/api/v1/containers/files",
        json={"compose": "services: {}", "dockerfile": "FROM x"},
    )
    assert outside.status_code == 200
    assert str(tmp_path) in outside.json()["project_dir"]

    readonly = TestClient(create_web_app(read_only=True))
    blocked = readonly.post(
        "/api/v1/containers/files",
        json={"compose": "services: {}", "dockerfile": "FROM x"},
    )
    assert blocked.status_code == 403
    assert "Read-only" in blocked.json()["detail"]
    assert readonly.get("/api/v1/containers/plan").status_code == 200
    assert artifacts.exists()


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


def test_reset_endpoints_preview_and_require_confirmation(web_env, monkeypatch):
    tmp_path, _ = web_env
    home = tmp_path / ".hobees"
    home.mkdir()
    (home / ".env").write_text("HOBEES_DATABASE_URL=x\n", encoding="utf-8")
    (home / "sessions").mkdir()

    monkeypatch.setattr(config, "_CONFIG_DIR", home)
    monkeypatch.setattr(settings, "skills_dir", home / "skills")
    monkeypatch.setattr(settings, "artifacts_root", home / "artifacts")

    client = TestClient(create_web_app())

    plan = client.get("/api/v1/reset/plan").json()
    assert [target["path"] for target in plan["targets"]] == [
        str(home / ".env"),
        str(home / "sessions"),
    ]
    assert plan["notes"], "the test database lives outside the config folder"

    # A reset without the recorded Y(es) answer is refused and nothing is removed.
    refused = client.post("/api/v1/reset", json={"include_artifacts": False, "confirmed": False})
    assert refused.status_code == 400
    assert (home / ".env").exists()

    # A page on another origin cannot wipe the slate through the browser.
    cross_site = client.post(
        "/api/v1/reset",
        json={"include_artifacts": False, "confirmed": True},
        headers={"Origin": "http://evil.example"},
    )
    assert cross_site.status_code == 403
    assert (home / ".env").exists()

    done = client.post("/api/v1/reset", json={"include_artifacts": True, "confirmed": True})
    assert done.status_code == 200
    body = done.json()
    assert body["success"] and body["removed"] and body["restart_required"]
    assert not (home / ".env").exists()
    assert not (home / "sessions").exists()

    # Read-only mode blocks the mutation, so the Studio panel cannot reset there.
    readonly = TestClient(create_web_app(read_only=True))
    assert readonly.post("/api/v1/reset", json={"confirmed": True}).status_code == 403

def test_quick_setup_templates_report_collisions_before_applying(web_env, monkeypatch):
    client = TestClient(create_web_app())

    templates = client.get("/api/v1/templates").json()
    assert templates
    research = next(t for t in templates if t["name"] == "research")
    assert research["counts"] == {
        "providers": 2,
        "bees": 2,
        "hives": 1,
        "memory": 0,
        "skills": 0,
        "assistant": 1,
    }
    assert research["conflicts"] == {}

    # Nothing exists yet, so applying needs no confirmation.
    applied = client.post("/api/v1/templates/apply", json={"template": "research", "confirmed": False})
    assert applied.status_code == 200
    body = applied.json()
    assert body["success"] and all(action["action"] == "create" for action in body["actions"])

    # The same template now collides with what it created: it must be confirmed.
    conflicts = next(t for t in client.get("/api/v1/templates").json() if t["name"] == "research")["conflicts"]
    assert conflicts["hives"] == ["research-team"]
    refused = client.post("/api/v1/templates/apply", json={"template": "research", "confirmed": False})
    assert refused.status_code == 409
    assert "research-team" in refused.json()["detail"]

    # skip leaves an entry the user tuned by hand alone; overwrite tramples it.
    client.put("/api/v1/bees/searcher", json={"role_description": "hand-tuned role"})
    skipped = client.post(
        "/api/v1/templates/apply",
        json={"template": "research", "on_conflict": "skip", "confirmed": True},
    ).json()
    assert all(action["action"] == "kept" for action in skipped["actions"])
    bee = next(b for b in client.get("/api/v1/bees").json() if b["name"] == "searcher")
    assert bee["role_description"] == "hand-tuned role"

    overwritten = client.post(
        "/api/v1/templates/apply",
        json={"template": "research", "on_conflict": "overwrite", "confirmed": True},
    ).json()
    assert all(action["action"] == "update" for action in overwritten["actions"])
    bee = next(b for b in client.get("/api/v1/bees").json() if b["name"] == "searcher")
    assert bee["role_description"] == "Gathers information and facts on a topic"

    assert client.post("/api/v1/templates/apply", json={"template": "nope", "confirmed": True}).status_code == 404
    assert client.post(
        "/api/v1/templates/apply", json={"template": "research", "on_conflict": "bogus", "confirmed": True}
    ).status_code == 400
    assert TestClient(create_web_app(read_only=True)).post(
        "/api/v1/templates/apply", json={"template": "research", "confirmed": True}
    ).status_code == 403


def test_provider_detection_reports_candidates_and_registers_only_picked_ones(web_env, monkeypatch, tmp_path):
    client = TestClient(create_web_app())

    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("hobees.core.provider_detector._port_open", lambda host, port, *a, **kw: port == 11434)
    monkeypatch.setattr("hobees.core.provider_detector._SENTINEL_FILE", tmp_path / "sentinel")

    detected = client.post("/api/v1/providers/detect").json()
    assert {c["alias"] for c in detected["candidates"]} == {"deepseek-main", "ollama-local"}
    assert all(not c["registered"] for c in detected["candidates"])
    assert detected["first_launch"] is True

    registered = client.post("/api/v1/providers/detect/register", json={"aliases": ["deepseek-main"]}).json()
    assert registered["success"] and registered["registered"] == ["deepseek-main"]
    assert [p["alias"] for p in client.get("/api/v1/providers").json()] == ["deepseek-main"]

    # Re-detection flags it as registered, and a second register keeps the existing row.
    again = client.post("/api/v1/providers/detect").json()
    assert {c["alias"]: c["registered"] for c in again["candidates"]}["deepseek-main"] is True
    second = client.post("/api/v1/providers/detect/register", json={"aliases": ["deepseek-main"]}).json()
    assert second["registered"] == [] and second["skipped"] == ["deepseek-main"]

    assert client.post("/api/v1/providers/detect/register", json={"aliases": ["not-a-candidate"]}).status_code == 400
    assert TestClient(create_web_app(read_only=True)).post("/api/v1/providers/detect").status_code == 403

def test_reset_deletes_a_database_file_inside_the_config_folder(web_env, monkeypatch):
    """The default hobees.db must be on the plan even when the env file holds no URL,
    and the engine pool is released before the file is removed."""
    tmp_path, _ = web_env
    home = tmp_path / ".hobees"
    home.mkdir()
    db_file = home / "hobees.db"
    db_file.write_text("db\n", encoding="utf-8")
    (home / ".env").write_text("# no HOBEES_DATABASE_URL here\n", encoding="utf-8")

    monkeypatch.setattr(config, "_CONFIG_DIR", home)
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "skills_dir", home / "skills")
    monkeypatch.setattr(settings, "artifacts_root", home / "artifacts")

    client = TestClient(create_web_app())
    plan = client.get("/api/v1/reset/plan").json()
    assert str(db_file) in [target["path"] for target in plan["targets"]]

    removed = client.post("/api/v1/reset", json={"confirmed": True}).json()
    assert removed["success"] and str(db_file) in removed["removed"]
    assert not db_file.exists()
    assert removed["restart_required"]

def test_container_plan_reports_the_generated_set_and_saves_it(web_env, monkeypatch):
    tmp_path, _ = web_env
    monkeypatch.setenv("HOBEES_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("hobees.core.container_prep.shutil.which", lambda _name: None)

    client = TestClient(create_web_app())
    plan = client.get("/api/v1/containers/plan").json()

    assert plan["config"]
    assert plan["entrypoint"].startswith("#!/bin/sh")
    assert "hobees init --config" in plan["entrypoint"]
    assert plan["pipeline_command"] == ["run", "--goal-file", "/data/goal.txt", "--json"]
    assert "./goal.txt:/data/goal.txt:ro" in plan["compose"]
    assert any("no goal set" in warning for warning in plan["warnings"])
    # The .env key checklist is part of the generated set: keys, no values.
    sample = client.post("/api/v1/containers/plan", json={"goal": "x", "api_key_envs": ["OPENAI_API_KEY"]}).json()["env_sample"]
    assert "OPENAI_API_KEY=" in sample and "POSTGRES_PASSWORD=" in sample
    assert "sk-" not in sample

    baked = client.post(
        "/api/v1/containers/plan",
        json={"goal": "Review src/", "goal_mode": "bake", "run_hive": "dev-team"},
    ).json()
    assert "COPY --chown=hobees:hobees goal.txt /data/goal.txt" in baked["dockerfile"]
    assert baked["pipeline_command"] == ["run", "--hive", "dev-team", "--goal-file", "/data/goal.txt", "--json"]

    # A prompt that looks like shell stays text: it is only ever written to the goal file.
    injection = client.post(
        "/api/v1/containers/plan",
        json={"goal": "`whoami`; $(id)", "goal_mode": "mount"},
    ).json()
    assert "whoami" not in injection["entrypoint"]

    saved = client.post(
        "/api/v1/containers/files",
        json={
            "compose": "services:\n  app:\n    build: .",
            "dockerfile": "FROM python:3.12-slim",
            "config": "providers: []",
            "entrypoint": "#!/bin/sh\nset -eu",
            "goal": "Review src/",
            "env_sample": "OPENAI_API_KEY=\n",
        },
    )
    assert saved.status_code == 200
    names = {Path(item).name for item in saved.json()["saved"]}
    assert names == {
        "compose.yaml",
        "Dockerfile",
        "hobees.yaml",
        "docker-entrypoint.sh",
        ".env.sample",
        "goal.txt",
    }

    # stdin mode has no goal file to write.
    stdin_saved = client.post(
        "/api/v1/containers/files",
        json={
            "compose": "services:\n  app:\n    build: .",
            "dockerfile": "FROM python:3.12-slim",
            "config": "providers: []",
            "entrypoint": "#!/bin/sh\nset -eu",
            "goal": "piped goal",
            "spec": {"goal_mode": "stdin", "goal": "piped goal"},
        },
    ).json()
    assert "goal.txt" not in {Path(item).name for item in stdin_saved["saved"]}

    # Generation only: no docker action route exists, so such a request can only
    # reach the SPA catch-all.
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("containers/action" in path for path in paths)


def test_container_plan_flags_an_empty_active_config(web_env, monkeypatch):
    tmp_path, _ = web_env
    monkeypatch.setenv("HOBEES_PROJECT_ROOT", str(tmp_path))
    client = TestClient(create_web_app())
    plan = client.get("/api/v1/containers/plan").json()
    assert any("active configuration is empty" in warning for warning in plan["warnings"])


def test_a_blank_model_is_resolved_the_way_the_ui_shows_it(web_env):
    client = TestClient(create_web_app())

    with_default = client.post(
        "/api/v1/providers",
        json={
            "alias": "has-default",
            "provider_type": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "api_key_env": "NONE",
            "default_model": "llama3",
        },
    ).json()

    # The Bee dialog shows a model as chosen; saving must store that same model.
    bee = client.post(
        "/api/v1/bees",
        json={
            "name": "bee-blank",
            "role_description": "Reads",
            "system_prompt": "",
            "provider_id": with_default["id"],
            "model_name": "",
            "temperature": 0,
            "thinking_level": "off",
            "tool_names": [],
            "require_approval": [],
        },
    )
    assert bee.status_code == 200
    assert bee.json()["model_name"] == "llama3"

    # Nothing to resolve: the request is refused instead of storing a Bee with no model.
    bare = client.post(
        "/api/v1/providers",
        json={"alias": "no-model", "provider_type": "openai", "api_key_env": "OPENAI_API_KEY"},
    ).json()
    refused = client.post(
        "/api/v1/bees",
        json={
            "name": "bee-no-model",
            "role_description": "Reads",
            "system_prompt": "",
            "provider_id": bare["id"],
            "model_name": "",
            "temperature": 0,
            "thinking_level": "off",
            "tool_names": [],
            "require_approval": [],
        },
    )
    assert refused.status_code == 400
    assert "has no model to use" in refused.json()["detail"]

    hive = client.post(
        "/api/v1/hives",
        json={
            "name": "hive-blank",
            "goal_description": "goal",
            "supervisor_provider_id": with_default["id"],
            "supervisor_model_name": "",
            "supervisor_prompt": "",
            "supervisor_thinking_level": "off",
            "is_dynamic": True,
            "project_path": "",
            "bee_ids": [],
        },
    )
    assert hive.status_code == 200
    assert hive.json()["supervisor_model_name"] == "llama3"
