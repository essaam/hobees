"""Tests for the Studio Containers tab backend (`hobees.core.container_prep`)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hobees.core import container_prep


class FakeResult:
    returncode = 0
    stdout = "started"
    stderr = ""


def test_compose_yaml_keeps_environment_names_not_values(tmp_path, monkeypatch):
    monkeypatch.setattr(container_prep.settings, "artifacts_root", tmp_path / "artifacts")
    monkeypatch.setattr(container_prep.settings, "skills_dir", tmp_path / "skills")
    monkeypatch.setenv("HOBEES_CONTAINER_NAME", "worker-1")

    spec = container_prep.default_spec(["OPENAI_API_KEY"])
    text = container_prep.compose_yaml(spec)
    parsed = yaml.safe_load(text)

    service = parsed["services"]["hobees"]
    assert service["container_name"] == "worker-1"
    assert service["environment"]["OPENAI_API_KEY"] == "${OPENAI_API_KEY}"
    assert "sk-" not in text
    assert service["profiles"] == ["runtime_only"]
    assert service["depends_on"]["db"]["condition"] == "service_healthy"
    assert parsed["volumes"]["postgres_data"] is None


def test_default_spec_uses_the_current_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(container_prep.settings, "artifacts_root", tmp_path / "artifacts")
    monkeypatch.setattr(container_prep.settings, "skills_dir", tmp_path / "skills")

    spec = container_prep.default_spec(["NONE", "GEMINI_API_KEY"])
    assert spec.resolved_volumes() == [
        f"./{(tmp_path / 'artifacts').as_posix()}:/data/artifacts",
        f"./{(tmp_path / 'skills').as_posix()}:/data/skills",
    ]
    assert spec.api_key_envs == ["GEMINI_API_KEY"]
    assert spec.warnings() == []


def test_invalid_service_name_is_reported_as_a_warning():
    spec = container_prep.ContainerSpec(service="Bad Service")
    assert any("valid compose service key" in warning for warning in spec.warnings())


def test_dockerfile_uses_non_root_user_and_no_dev_extras():
    text = container_prep.dockerfile_text(container_prep.ContainerSpec())
    assert text.startswith("FROM python:3.12-slim")
    assert "uv sync --no-dev" in text
    assert "USER hobees" in text
    assert 'ENTRYPOINT ["hobees"]' in text
    assert 'CMD ["web", "--host", "0.0.0.0", "--port", "8420"]' in text


def test_validate_compose_reports_missing_services_and_literal_secrets():
    _, warnings = container_prep.validate_compose("services: {}\n")
    assert any("would start nothing" in warning for warning in warnings)

    _, warnings = container_prep.validate_compose(
        "services:\n  app:\n    image: app\n    environment:\n      OPENAI_API_KEY: sk-live-key\n"
    )
    assert any("literal value" in warning for warning in warnings)

    _, warnings = container_prep.validate_compose(
        "services:\n  app:\n    build: .\n    privileged: true\n"
    )
    assert any("privileged" in warning for warning in warnings)


def test_validate_compose_rejects_broken_yaml():
    with pytest.raises(ValueError, match="Invalid YAML"):
        container_prep.validate_compose("services: [unclosed")


def test_only_allowlisted_compose_actions_can_be_run():
    assert container_prep.compose_command("up") == [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "up",
        "-d",
    ]
    assert container_prep.compose_command("logs", service="hobees", tail=20) == [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "logs",
        "--tail",
        "20",
        "hobees",
    ]
    for forbidden in ("exec", "run", "cp", "system"):
        with pytest.raises(ValueError, match="action must be one of"):
            container_prep.compose_command(forbidden)


def test_run_compose_never_shells_and_requires_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(container_prep.shutil, "which", lambda _name: None)
    with pytest.raises(ValueError, match="docker is not available"):
        container_prep.run_compose("up", tmp_path)

    calls: dict[str, object] = {}

    def runner(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return FakeResult()

    monkeypatch.setattr(container_prep.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(container_prep.subprocess, "run", runner)

    assert container_prep.run_compose("ps", tmp_path) == "started"
    assert calls["argv"] == ["docker", "compose", "-f", "compose.yaml", "ps"]
    assert calls["kwargs"]["shell"] is False
    assert Path(calls["kwargs"]["cwd"]) == tmp_path.resolve()


def test_run_compose_reports_a_failed_command(monkeypatch):
    class Failed(FakeResult):
        returncode = 1
        stdout = ""
        stderr = "no such service"

    monkeypatch.setattr(container_prep.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(container_prep.subprocess, "run", lambda *_a, **_k: Failed())

    with pytest.raises(RuntimeError, match="no such service"):
        container_prep.run_compose("up", Path("."))
