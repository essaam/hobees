"""Tests for the Studio Containers tab backend (`hobees.core.container_prep`)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import yaml

from hobees.core import container_prep


def test_compose_yaml_keeps_environment_names_not_values(tmp_path, monkeypatch):
    monkeypatch.setattr(container_prep.settings, "artifacts_root", tmp_path / "artifacts")
    monkeypatch.setattr(container_prep.settings, "skills_dir", tmp_path / "skills")
    monkeypatch.setenv("HOBEES_CONTAINER_NAME", "worker-1")

    spec = container_prep.default_spec(["OPENAI_API_KEY"], run_hive="dev-team")
    text = container_prep.compose_yaml(spec)
    parsed = yaml.safe_load(text)

    service = parsed["services"]["hobees"]
    spec_postgres_service_name = spec.postgres_service_name
    # Nothing from the author's machine is baked in: the name is read at run time.
    assert service["container_name"] == container_prep.CONTAINER_NAME_PLACEHOLDER
    assert socket.gethostname() not in text
    assert service["environment"]["OPENAI_API_KEY"] == "${OPENAI_API_KEY}"
    assert "sk-" not in text
    assert service["profiles"] == ["pipeline"]
    assert service["depends_on"][spec_postgres_service_name]["condition"] == "service_healthy"
    assert parsed["volumes"]["postgres_data"] is None
    # The container runs the goal, and the goal is mounted read-only by default.
    assert "./goal.txt:/data/goal.txt:ro" in service["volumes"]
    # Nothing is baked as a default command: the entrypoint script decides.
    assert "command" not in service
    assert service["profiles"] == ["pipeline"]
    # The image ENTRYPOINT is the generated script, so compose must not override it.
    assert "entrypoint" not in service


def test_default_spec_uses_the_current_settings(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("HOBEES_PROJECT_ROOT", str(root))
    monkeypatch.setattr(container_prep.settings, "artifacts_root", root / "artifacts")
    monkeypatch.setattr(container_prep.settings, "skills_dir", tmp_path / "skills")

    spec = container_prep.default_spec(["NONE", "GEMINI_API_KEY"])
    # Generated files hold relative paths only - a path from the author's machine would make
    # the file unusable for anyone else.
    assert spec.resolved_volumes() == [
        "./artifacts:/data/artifacts",
        "./skills:/data/skills",
        "./goal.txt:/data/goal.txt:ro",
    ]
    assert str(tmp_path) not in container_prep.compose_yaml(spec)
    assert "C:/" not in container_prep.compose_yaml(spec)
    assert spec.api_key_envs == ["GEMINI_API_KEY"]
    assert spec.ports == ["6543:6543"]
    assert any("no goal set" in warning for warning in spec.warnings())
    assert not any("valid compose service key" in warning for warning in spec.warnings())


def test_bake_mode_copies_the_goal_into_the_image(tmp_path, monkeypatch):
    monkeypatch.setenv("HOBEES_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(container_prep.settings, "artifacts_root", tmp_path / "artifacts")
    monkeypatch.setattr(container_prep.settings, "skills_dir", tmp_path / "skills")

    spec = container_prep.ContainerSpec(goal_mode="bake", goal="Review src/", run_hive="dev-team")
    dockerfile = container_prep.dockerfile_text(spec)
    volumes = spec.resolved_volumes()

    assert f"COPY --chown=hobees:hobees goal.txt {container_prep.GOAL_TARGET}" in dockerfile
    assert "./goal.txt:/data/goal.txt:ro" not in volumes
    assert spec.goal_mode in container_prep.GOAL_MODES

    # stdin mode has no file to mount or bake: the goal arrives through the pipe.
    stdin_spec = container_prep.ContainerSpec(goal_mode="stdin")
    assert stdin_spec.pipeline_command() == ["run", "-", "--json"]
    assert stdin_spec.resolved_command() == []  # an override only
    assert "./goal.txt:/data/goal.txt:ro" not in stdin_spec.resolved_volumes()


def test_entrypoint_initialises_then_runs_the_goal():
    spec = container_prep.ContainerSpec(run_hive="dev-team", goal="`whoami` in the prompt; $(id)")
    script = container_prep.entrypoint_text(spec)

    assert script.startswith("#!/bin/sh")
    assert "hobees init --config" in script
    assert 'exec hobees "$@"' in script
    assert "--goal-file" in script
    # The prompt text is never written into the script: a goal cannot be read as shell.
    assert "whoami" not in script
    assert "$(id)" not in script
    assert spec.goal not in script


def test_dockerfile_follows_the_repo_dockerfile_and_installs_from_pypi():
    text = container_prep.dockerfile_text(container_prep.ContainerSpec(goal="x"))
    assert text.startswith("FROM python:3.12-slim")
    # In operation hobees is installed with `uv tool install`, so the image has no source tree.
    assert "RUN uv tool install hobees" in text
    assert "COPY src" not in text
    assert "uv sync" not in text
    assert "RUN pip install --no-cache-dir uv" in text
    assert "USER hobees" in text
    # User and directories are created before the switch to user space.
    assert text.index("groupadd") < text.index("USER hobees") < text.index("RUN uv tool install")
    assert 'ENV PATH="/home/hobees/.local/bin:$PATH"' in text
    assert f'ENTRYPOINT ["{container_prep.CONTAINER_ENTRYPOINT}"]' in text
    assert text.count(chr(92)) >= 3  # the RUN continuation lines stay one instruction
    assert "COPY --chown=hobees:hobees hobees.yaml /data/config/hobees.yaml" in text
    assert "COPY --chown=hobees:hobees docker-entrypoint.sh /entrypoint.sh" in text
    assert text.count(chr(92)) >= 3  # the RUN continuation lines stay one instruction

    # No CMD line: the script is the single place that decides what runs.
    assert "CMD [" not in text
    assert "# No CMD on purpose" in text  # the reason is written in the generated file
    assert container_prep.ContainerSpec(goal="x").resolved_command() == []
    assert container_prep.ContainerSpec(goal="x").pipeline_command()[:2] == ["run", "--goal-file"]
    # An explicit override is what compose and the script accept.
    override = container_prep.ContainerSpec(goal="x", command=["run", "-"])
    assert yaml.safe_load(container_prep.compose_yaml(override))["services"]["hobees"]["command"] == ["run", "-"]


def test_web_port_default_follows_the_cli_default():
    import inspect

    from hobees.cli import main

    defaults = dict(zip(inspect.signature(main.web).parameters, main.web.__defaults__))
    assert defaults["port"].default == container_prep.DEFAULT_WEB_PORT == 6543


def test_invalid_service_name_is_reported_as_a_warning():
    spec = container_prep.ContainerSpec(service="Bad Service")
    assert any("valid compose service key" in warning for warning in spec.warnings())

    bad_mode = container_prep.ContainerSpec(goal_mode="telepathy", goal="x")
    assert any("goal_mode" in warning for warning in bad_mode.warnings())

    sneaky = container_prep.ContainerSpec(goal="x", goal_file="../escape.txt")
    assert any("cannot be written at the project root" in warning for warning in sneaky.warnings())


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


def test_save_project_files_writes_the_generated_set_inside_the_root(tmp_path):
    written = container_prep.save_project_files(
        {
            "compose.yaml": "services:\n  app:\n    build: .\n",
            "Dockerfile": "FROM python:3.12-slim\n",
            "hobees.yaml": "providers: []\n",
            "goal.txt": "Review src/\n",
            "docker-entrypoint.sh": "#!/bin/sh\nset -eu\n",
        },
        tmp_path,
    )
    assert sorted(p.name for p in written) == [
        "Dockerfile",
        "compose.yaml",
        "docker-entrypoint.sh",
        "goal.txt",
        "hobees.yaml",
    ]

    # Empty content is skipped, and any name that could leave the root is refused:
    # names cannot contain separators, so a request cannot steer the write anywhere else.
    assert container_prep.save_project_files({"compose.yaml": "", "goal.txt": "x"}, tmp_path) == [
        tmp_path / "goal.txt"
    ]
    for attempt in ("../escape.yaml", "sub/dir.yaml"):
        with pytest.raises(ValueError, match="cannot be written"):
            container_prep.save_project_files({attempt: "x"}, tmp_path)


def test_the_web_service_is_optional_and_commented_out_by_default():
    spec = container_prep.ContainerSpec(goal="x")
    text = container_prep.compose_yaml(spec)
    parsed = yaml.safe_load(text)
    # Commented out by default: a pipeline does not need the dashboard running in the container.
    assert "web" not in parsed["services"]
    assert "# Optional: the web app is not needed to run a goal" in text
    assert "# web:" in text
    assert "6543:6543" in text

    opted = container_prep.ContainerSpec(goal="x", include_web=True)
    services = yaml.safe_load(container_prep.compose_yaml(opted))["services"]
    assert services["web"]["profiles"] == ["ui"]
    assert services["web"]["command"] == ["web", "--host", "0.0.0.0", "--port", "6543"]


def test_an_explicit_container_name_still_wins():
    spec = container_prep.ContainerSpec(goal="x", container_name="worker-1")
    parsed = yaml.safe_load(container_prep.compose_yaml(spec))
    assert parsed["services"]["hobees"]["container_name"] == "worker-1"

def test_paths_are_relative_and_one_service_name_is_used_everywhere():
    spec = container_prep.ContainerSpec(goal="x", api_key_envs=["OPENAI_API_KEY"])
    text = container_prep.compose_yaml(spec)
    parsed = yaml.safe_load(text)
    service = parsed["services"]["hobees"]

    # A bare name would resolve against the wrong place; a leading ./ keeps it relative to
    # the folder the compose file lives in.
    assert service["env_file"] == ["./.env"]
    assert service["build"]["dockerfile"] == "./Dockerfile"
    assert all(item.startswith("./") for item in service["volumes"])

    # The service key and the host name the container resolves are the same value.
    assert spec.postgres_service_name in parsed["services"]
    assert f"@{spec.postgres_service_name}:5432" in text
    assert service["environment"]["OPENAI_API_KEY"] == "${OPENAI_API_KEY}"
    assert not any(key.startswith("sk-") for key in service["environment"])


def test_paths_defined_by_the_dockerfile_are_not_redefined_in_compose():
    spec = container_prep.ContainerSpec(goal="x", goal_mode="mount")
    compose = yaml.safe_load(container_prep.compose_yaml(spec))["services"]["hobees"]
    dockerfile = container_prep.dockerfile_text(spec)

    # Each path is defined once: the Dockerfile ENV, and the script reads it from the env.
    assert f"ENV HOBEES_CONFIG_PATH={container_prep.CONFIG_TARGET}" in dockerfile
    assert f"ENV HOBEES_GOAL_FILE={container_prep.GOAL_TARGET}" in dockerfile
    assert "HOBEES_CONFIG_PATH" not in compose["environment"]
    assert "HOBEES_GOAL_FILE" not in compose["environment"]

    script = container_prep.entrypoint_text(spec)
    assert '${HOBEES_CONFIG_PATH:-' in script
    assert '${HOBEES_GOAL_FILE:-' in script

    # stdin mode has no goal file, so no goal path is defined for it.
    stdin = container_prep.ContainerSpec(goal_mode="stdin")
    assert "HOBEES_GOAL_FILE" not in container_prep.dockerfile_text(stdin)


def test_env_sample_lists_the_keys_without_values():
    spec = container_prep.ContainerSpec(
        goal="x",
        api_key_envs=["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "NONE"],
    )
    sample = container_prep.env_sample_text(spec)

    # Required: the provider keys and the password the DB URL cannot default.
    required_part = sample.split("# Required")[1].split("# Referenced")[0]
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "POSTGRES_PASSWORD"):
        assert f"{key}=" in required_part

    # Names with a default in compose.yaml are listed separately, still without values.
    optional_part = sample.split("# Referenced")[1]
    for key in ("HOBEES_UID", "HOBEES_GID", "POSTGRES_USER", "HOBEES_CONTAINER_NAME"):
        assert f"{key}=" in optional_part

    assert "sk-" not in sample
    assert ".env.sample" in container_prep.generated_files(spec, {})


def test_the_env_sample_is_written_with_the_generated_set(tmp_path, monkeypatch):
    monkeypatch.setenv("HOBEES_PROJECT_ROOT", str(tmp_path))
    spec = container_prep.ContainerSpec(goal="x", api_key_envs=["OPENAI_API_KEY"])
    sample = container_prep.env_sample_text(spec)
    contents = {
        ".env.sample": sample,
        "compose.yaml": container_prep.compose_yaml(spec),
        "Dockerfile": container_prep.dockerfile_text(spec),
        "hobees.yaml": "providers: []",
        "docker-entrypoint.sh": container_prep.entrypoint_text(spec),
    }
    files = container_prep.generated_files(spec, contents)
    written = container_prep.save_project_files(files, tmp_path)
    names = {Path(path).name for path in written}
    assert names == {
        "compose.yaml",
        "Dockerfile",
        "hobees.yaml",
        "docker-entrypoint.sh",
        ".env.sample",
    }
