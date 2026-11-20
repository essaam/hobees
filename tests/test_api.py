"""Unit tests for Phase 6 FastAPI endpoints."""

import json
import threading
import time
from contextlib import contextmanager
from importlib.metadata import version as package_version
from types import SimpleNamespace

from fastapi.testclient import TestClient

import hobees.api.app as api_module
from hobees.api.app import create_app


def test_api_version_matches_package_metadata():
    assert create_app().version == package_version("hobees")


def test_health_endpoints():
    client = TestClient(create_app())
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_api = client.get("/api/health")
    assert res_api.status_code == 200
    assert res_api.json()["status"] == "ok"


def test_stats_endpoints():
    client = TestClient(create_app())
    res = client.get("/stats")
    assert res.status_code == 200
    data = res.json()
    assert "totals" in data
    assert "data" in data

    res_api = client.get("/api/stats?window=all&group_by=bee")
    assert res_api.status_code == 200


def test_stats_recent_endpoints():
    client = TestClient(create_app())
    res = client.get("/stats/recent?limit=5")
    assert res.status_code == 200
    assert "events" in res.json()

    res_api = client.get("/api/stats/recent?limit=5")
    assert res_api.status_code == 200


def test_runs_active_endpoints():
    client = TestClient(create_app())
    res = client.get("/runs/active")
    assert res.status_code == 200
    assert "runs" in res.json()

    res_api = client.get("/api/runs/active")
    assert res_api.status_code == 200


def test_roster_endpoints():
    client = TestClient(create_app())
    res = client.get("/roster")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert "bees" in data
    assert "hives" in data

    res_api = client.get("/api/roster")
    assert res_api.status_code == 200
    assert res_api.json() == data


def test_runs_history_endpoints():
    client = TestClient(create_app())
    res = client.get("/runs?limit=10")
    assert res.status_code == 200
    assert "runs" in res.json()

    res_api = client.get("/api/runs?limit=10")
    assert res_api.status_code == 200


def test_usage_stream_endpoints():
    client = TestClient(create_app())
    res = client.get("/usage/stream?iterations=1")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    assert "data: " in res.text

    res_api = client.get("/api/usage/stream?iterations=1")
    assert res_api.status_code == 200
    assert "text/event-stream" in res_api.headers["content-type"]
    assert "data: " in res_api.text


def test_run_trace_stream():
    client = TestClient(create_app())
    # Test trace stream with short timeout
    res = client.get("/runs/nonexistent_thread/stream?timeout=0.1")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    res_api = client.get("/api/runs/nonexistent_thread/stream?timeout=0.1")
    assert res_api.status_code == 200
    assert "text/event-stream" in res_api.headers["content-type"]


def test_run_trace_stream_replays_custom_artifact_directory(monkeypatch, tmp_path):
    thread_id = "custom-artifact-thread"
    artifacts_dir = tmp_path / "custom-run"
    traces_dir = artifacts_dir / "traces"
    traces_dir.mkdir(parents=True)
    event = {
        "thread_id": thread_id,
        "hive_name": "custom-hive",
        "event_type": "HIVE_COMPLETE",
        "source": "system",
        "payload": {},
    }
    (traces_dir / f"{thread_id}.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8"
    )

    class Session:
        def query(self, model):
            assert model is api_module.Run
            return self

        def filter_by(self, **_):
            return self

        def first(self):
            return SimpleNamespace(
                status="completed",
                artifacts_dir=str(artifacts_dir),
                hive_id=7,
            )

        def get(self, model, _):
            assert model is api_module.Hive
            return SimpleNamespace(name="custom-hive", project_path=None)

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(api_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        "hobees.config.settings.artifacts_root", tmp_path / "default-artifacts"
    )

    response = TestClient(create_app()).get(
        f"/api/runs/{thread_id}/stream?timeout=0.1"
    )

    assert response.status_code == 200
    assert json.dumps(event) in response.text


def test_run_trace_stream_polls_trace_file_from_other_process(monkeypatch, tmp_path):
    thread_id = "live-custom-thread"
    artifacts_dir = tmp_path / "live-run"
    traces_dir = artifacts_dir / "traces"
    traces_dir.mkdir(parents=True)
    trace_file = traces_dir / f"{thread_id}.jsonl"
    start_event = {
        "thread_id": thread_id,
        "hive_name": "live-hive",
        "event_type": "HIVE_START",
        "source": "system",
        "payload": {},
    }
    complete_event = {
        **start_event,
        "event_type": "HIVE_COMPLETE",
    }
    trace_file.write_text(json.dumps(start_event) + "\n", encoding="utf-8")

    class Query:
        def filter_by(self, **_):
            return self

        def first(self):
            return SimpleNamespace(
                status="running",
                artifacts_dir=str(artifacts_dir),
                hive_id=8,
            )

    class Session:
        def query(self, model):
            assert model is api_module.Run
            return Query()

        def get(self, model, _):
            assert model is api_module.Hive
            return SimpleNamespace(name="live-hive", project_path=None)

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(api_module, "session_scope", fake_session_scope)

    def append_completion():
        time.sleep(0.1)
        with trace_file.open("a", encoding="utf-8") as trace:
            trace.write(json.dumps(complete_event) + "\n")

    writer = threading.Thread(target=append_completion)
    writer.start()
    response = TestClient(create_app()).get(
        f"/api/runs/{thread_id}/stream?timeout=3"
    )
    writer.join()

    assert response.status_code == 200
    assert json.dumps(start_event) in response.text
    assert json.dumps(complete_event) in response.text
