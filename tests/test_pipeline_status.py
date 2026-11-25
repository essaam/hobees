"""Tests for the pipeline-facing outcome signal: exit code, and the run manifest.

A short-lived container tells a pipeline manager how it ended through its exit code, and
`hobees pipeline status` is the second, richer reading of the same outcome.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from hobees.cli import pipeline_cmd
from hobees.cli.main import app
from hobees.core import pipeline_status

runner = CliRunner()


def test_status_maps_to_the_exit_code_a_pipeline_reads():
    assert pipeline_status.pipeline_exit_code("completed") == 0
    assert pipeline_status.pipeline_exit_code("failed") == 1
    assert pipeline_status.pipeline_exit_code("awaiting_approval") == 2
    assert pipeline_status.pipeline_exit_code("running") == 3
    # An unknown status cannot be assumed successful.
    assert pipeline_status.pipeline_exit_code("weird") == 1
    assert pipeline_status.pipeline_exit_code(None) == 1
    assert pipeline_status.is_terminal("failed")
    assert not pipeline_status.is_terminal("running")


def test_manifest_entry_reads_last_run_then_the_runs_list(tmp_path):
    path = tmp_path / "run_manifest.json"
    path.write_text(
        json.dumps({"hive_name": "dev-team", "last_run": {"status": "failed", "error": "boom"}}),
        encoding="utf-8",
    )
    entry = pipeline_status.manifest_entry(pipeline_status.read_manifest(path))
    assert entry["status"] == "failed"
    assert entry["error"] == "boom"

    history = tmp_path / "history.json"
    history.write_text(json.dumps({"runs": [{"status": "completed"}]}), encoding="utf-8")
    assert pipeline_status.manifest_entry(pipeline_status.read_manifest(history))["status"] == "completed"

    assert pipeline_status.read_manifest(tmp_path / "missing.json") is None
    assert pipeline_status.read_manifest(tmp_path / "bad.json") is None


def test_pipeline_status_reads_the_manifest_and_returns_its_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("hobees.config.settings.artifacts_root", tmp_path)
    hive_dir = tmp_path / "dev-team"
    hive_dir.mkdir()
    (hive_dir / "run_manifest.json").write_text(
        json.dumps({"hive_name": "dev-team", "last_run": {"status": "failed", "error": "provider timeout", "thread_id": "abc"}}),
        encoding="utf-8",
    )

    assert pipeline_cmd.cmd_pipeline_status(hive="dev-team") == 1

    result = runner.invoke(app, ["pipeline", "status", "--hive", "dev-team", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["exit_code"] == 1
    assert payload["error"] == "provider timeout"


def test_pipeline_status_waits_for_a_terminal_run(tmp_path, monkeypatch):
    monkeypatch.setattr("hobees.config.settings.artifacts_root", tmp_path)
    hive_dir = tmp_path / "dev-team"
    hive_dir.mkdir()
    manifest = hive_dir / "run_manifest.json"
    manifest.write_text(json.dumps({"last_run": {"status": "running"}}), encoding="utf-8")

    # No wait window: the current state is reported, and a run that is still in flight is
    # not a success, so the pipeline sees code 3.
    assert pipeline_cmd.cmd_pipeline_status(hive="dev-team") == 3

    manifest.write_text(json.dumps({"last_run": {"status": "completed"}}), encoding="utf-8")
    assert pipeline_cmd.cmd_pipeline_status(hive="dev-team", poll=1, timeout=5) == 0


def test_pipeline_status_can_read_the_run_row_when_no_manifest_exists(monkeypatch, tmp_path):
    from hobees.db.models import Run
    from hobees.db.session import session_scope

    monkeypatch.setattr("hobees.config.settings.artifacts_root", tmp_path / "empty")
    with session_scope() as session:
        # The test database is shared across the session, so clear the row first.
        session.query(Run).filter(Run.thread_id == "pipeline-status-thread").delete()
        session.add(
            Run(
                thread_id="pipeline-status-thread",
                mode="hive",
                goal="check",
                status="awaiting_approval",
                artifacts_dir=str(tmp_path),
                started_at=datetime.now(timezone.utc),
            )
        )

    assert pipeline_cmd.cmd_pipeline_status(thread_id="pipeline-status-thread") == 2


def test_pipeline_status_reports_when_nothing_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr("hobees.config.settings.artifacts_root", tmp_path)
    assert pipeline_cmd.cmd_pipeline_status(hive="nothing-here") == 1


def test_the_manifest_carries_the_exit_code_and_the_entrypoint_keeps_it():
    from hobees.core import container_prep

    script = container_prep.entrypoint_text(container_prep.ContainerSpec(goal="x"))
    assert "set -eu" in script
    assert "exec run" in script
    assert "0 completed, 1 failed, 2 stopped for an" in script
    assert "approval a headless run cannot answer" in script

    manifest_source = (
        (Path(__file__).resolve().parents[1] / "src" / "hobees" / "cli" / "hive_cmd.py").read_text(encoding="utf-8")
    )
    assert '"exit_code": pipeline_exit_code(final_status)' in manifest_source
    assert "raise typer.Exit(code=code)" in manifest_source
