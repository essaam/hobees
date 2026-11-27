"""Container preparation: compose/Dockerfile generation and guarded lifecycle actions.

This is the deployment side of Studio: the generated files carry environment-variable
*names*, never secret values, and nothing here runs `docker` - the tab writes files and
the pipeline (or a person) executes them. The container's exit code is how a pipeline
learns the outcome, so the entrypoint script uses `set -eu` and `exec`.

The generated set carries the configuration the user is happy with right now:
`hobees.yaml` and the entrypoint script are copied into the image, the entrypoint
initialises the schema with that config and then runs the goal. The goal reaches the
container as a read-only mount (default), a baked file (opt-in) or stdin - the prompt
text is never written into the entrypoint script, so it can never be read as shell.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from hobees.config import settings

DEFAULT_BASE_IMAGE = "python:3.12-slim"
DEFAULT_COMPOSE_FILE = "compose.yaml"
DEFAULT_DOCKERFILE = "Dockerfile"
DEFAULT_ENTRYPOINT_FILE = "docker-entrypoint.sh"
DEFAULT_CONFIG_FILE = "hobees.yaml"
DEFAULT_GOAL_FILE = "goal.txt"
DEFAULT_ENV_SAMPLE_FILE = ".env.sample"
DEFAULT_ENV_SAMPLE_FILE = ".env.sample"

#: `hobees web` binds 6543 by default, so the container publishes the same port.
DEFAULT_WORKING_DIR = "/home/hobees"
DEFAULT_WEB_PORT = 6543

#: How the goal reaches the container.
GOAL_MODES: tuple[str, ...] = ("mount", "bake", "stdin")
GOAL_TARGET = "/data/goal.txt"
CONFIG_TARGET = "/data/config/hobees.yaml"
CONTAINER_ENTRYPOINT = "/entrypoint.sh"
CONTAINER_USER = "hobees:hobees"
#: Every path written into a generated file is relative to the project root or inside the
#: image - a path from the author's machine must never end up in a committed file.
DEFAULT_ARTIFACTS_MOUNT = "./artifacts:/data/artifacts"
DEFAULT_SKILLS_MOUNT = "./skills:/data/skills"
#: The name is read from the environment at run time instead of being baked in here.
CONTAINER_NAME_PLACEHOLDER = "${HOBEES_CONTAINER_NAME:-hobees}"

_SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_FILE_NAME = re.compile(r"^\.{0,1}[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET_LIKE = re.compile(r"(?:api[_-]?key|token|secret|password|credential)", re.IGNORECASE)


class ContainerSpec(BaseModel):
    """One container definition plus the project settings it runs under."""

    project: str = "hobees"
    service: str = "hobees"
    image: str = "hobees:local"
    container_name: str = ""
    base_image: str = DEFAULT_BASE_IMAGE
    working_dir: str = DEFAULT_WORKING_DIR
    user: str = "${HOBEES_UID:-1000}:${HOBEES_GID:-1000}"
    #: Empty means the image's own ENTRYPOINT (the generated script) is used.
    entrypoint: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    profiles: list[str] = Field(default_factory=lambda: ["pipeline"])
    restart: str = "unless-stopped"
    ports: list[str] = Field(default_factory=lambda: [f"{DEFAULT_WEB_PORT}:{DEFAULT_WEB_PORT}"])
    volumes: list[str] = Field(default_factory=list)
    #: Environment variables the container reads. Values stay `${NAME}` references so
    #: the generated file never contains a key.
    env: dict[str, str] = Field(default_factory=dict)
    api_key_envs: list[str] = Field(default_factory=list)
    include_db: bool = True
    db_image: str = "postgres:16-alpine"
    db_volume: str = "postgres_data"
    #: The compose service key and the host name the container resolves; one value, used in both places.
    postgres_service_name: str = "postgres"
    web_service_name: str = "web"

    # --- What the container carries and runs ---
    #: The active configuration the user is happy with, exported as `hobees.yaml`.
    config_file: str = DEFAULT_CONFIG_FILE
    #: The goal prompt and how it reaches the container: mount (default), bake, stdin.
    #: The text is stored as a file, never written into the entrypoint script.
    goal: str = ""
    goal_file: str = DEFAULT_GOAL_FILE
    goal_mode: str = "mount"
    #: Hive the pipeline runs; empty means the Queen/auto mode.
    run_hive: str = ""
    #: The entrypoint script initializes the schema with the config before the goal.
    run_init: bool = True
    entrypoint_file: str = DEFAULT_ENTRYPOINT_FILE
    #: Running the web app from the container is optional: it stays commented out in
    #: the generated compose file unless the user asks for it.
    include_web: bool = False

    def resolved_container_name(self) -> str:
        return self.container_name or CONTAINER_NAME_PLACEHOLDER

    def goal_mount(self) -> str | None:
        """Read-only goal mount - the pipeline default, so a goal can change without a rebuild."""
        if self.goal_mode != "mount":
            return None
        return f"./{self.goal_file}:{GOAL_TARGET}:ro"

    def resolved_volumes(self) -> list[str]:
        mounts = list(self.volumes) or [DEFAULT_ARTIFACTS_MOUNT, DEFAULT_SKILLS_MOUNT]
        goal = self.goal_mount()
        if goal and goal not in mounts:
            mounts.append(goal)
        return mounts

    def pipeline_command(self) -> list[str]:
        """What the entrypoint script runs. Shown so CI can mirror it - it is not baked as
        `CMD`, because the script is the single place that decides what happens."""
        args = ["run"]
        if self.run_hive:
            args.extend(["--hive", self.run_hive])
        if self.goal_mode in ("mount", "bake"):
            args.extend(["--goal-file", GOAL_TARGET])
        else:
            args.append("-")
        args.append("--json")
        return args

    def resolved_command(self) -> list[str]:
        """An explicit override only. Left empty, the entrypoint script's own default runs."""
        return list(self.command)

    def resolved_env(self) -> dict[str, str]:
        env = dict(self.env)
        env.setdefault("HOBEES_ARTIFACTS_ROOT", "/data/artifacts")
        env.setdefault("HOBEES_SKILLS_DIR", "/data/skills")
        # HOBEES_CONFIG_PATH and HOBEES_GOAL_FILE are set by the Dockerfile ENV, so they
        # are not written here as well; the entrypoint script reads them from the env.
        if self.run_hive:
            env.setdefault("HOBEES_RUN_HIVE", self.run_hive)
        if self.include_db:
            env.setdefault(
                "HOBEES_DATABASE_URL",
                "postgresql+psycopg://${POSTGRES_USER:-hobees}:${POSTGRES_PASSWORD}@"
                f"{self.postgres_service_name}:5432/${{POSTGRES_DB:-hobees}}",
            )
        for name in self.api_key_envs:
            env.setdefault(name, f"${{{name}}}")
        return env

    def warnings(self) -> list[str]:
        notes: list[str] = []
        if not _SERVICE_NAME.match(self.service):
            notes.append(f"service name {self.service!r} is not a valid compose service key")
        if not self.profiles:
            notes.append("no profiles set: a plain `docker compose up` would start this service")
        if self.goal_mode not in GOAL_MODES:
            notes.append(f"goal_mode {self.goal_mode!r} must be one of {', '.join(GOAL_MODES)}")
        for name in (self.config_file, self.goal_file, self.entrypoint_file):
            if not _FILE_NAME.match(name):
                notes.append(f"file name {name!r} cannot be written at the project root")
        if not self.goal.strip():
            notes.append(
                "no goal set: the container would start with nothing to run - pipe one "
                "(`docker compose run -T --rm --profile pipeline <service>`) or fill the goal field"
            )
        for key, value in self.resolved_env().items():
            if _SECRET_LIKE.search(key) and not str(value).startswith("${"):
                notes.append(f"{key} is written as a literal value; use a ${{{key}}} reference instead")
        return notes


def compose_document(spec: ContainerSpec) -> dict[str, Any]:
    service: dict[str, Any] = {
        # Every host path is relative to the compose file: "./", not a bare name.
        "build": {"context": ".", "dockerfile": "./" + DEFAULT_DOCKERFILE},
        "image": spec.image,
        "container_name": spec.resolved_container_name(),
        "user": spec.user,
        "working_dir": spec.working_dir,
        "env_file": ["./.env"],
        "environment": spec.resolved_env(),
        "volumes": spec.resolved_volumes(),
        "init": True,
    }
    # Only an override the user typed is written: the entrypoint script already runs
    # init then the goal, so a default `command` would duplicate that decision.
    if spec.command:
        service["command"] = list(spec.command)
    if spec.entrypoint:
        service["entrypoint"] = list(spec.entrypoint)
    if spec.profiles:
        service["profiles"] = spec.profiles
    if spec.ports:
        service["ports"] = spec.ports
    if spec.restart:
        service["restart"] = spec.restart

    document: dict[str, Any] = {"services": {spec.service: service}}

    if spec.include_db:
        document["services"][spec.postgres_service_name] = {
            "image": spec.db_image,
            "environment": {
                "POSTGRES_DB": "${POSTGRES_DB:-hobees}",
                "POSTGRES_USER": "${POSTGRES_USER:-hobees}",
                "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}",
            },
            "volumes": [f"{spec.db_volume}:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\""],
                "interval": "5s",
                "timeout": "5s",
                "retries": 10,
                "start_period": "5s",
            },
        }
        service["depends_on"] = {spec.postgres_service_name: {"condition": "service_healthy"}}
        document["volumes"] = {spec.db_volume: None}

    if spec.include_web:
        # Only when asked for: a pipeline does not need the web app running in the container.
        document["services"][spec.web_service_name] = {
            "build": {"context": ".", "dockerfile": "./" + DEFAULT_DOCKERFILE},
            "image": spec.image,
            "profiles": ["ui"],
            "env_file": ["./.env"],
            "ports": [f"{DEFAULT_WEB_PORT}:{DEFAULT_WEB_PORT}"],
            "command": ["web", "--host", "0.0.0.0", "--port", str(DEFAULT_WEB_PORT)],
        }

    return document


def optional_web_block(spec: ContainerSpec) -> str:
    """The commented-out web service - running the web app in the container is optional."""
    if spec.include_web:
        return ""
    port = DEFAULT_WEB_PORT
    return (
        "\n# Optional: the web app is not needed to run a goal, so this stays commented out.\n"
        "# Uncomment to serve the dashboard from the container; the keys still come from .env.\n"
        f"# {spec.web_service_name}:\n"
        "#   build:\n"
        "#     context: .\n"
        f"#     dockerfile: ./{DEFAULT_DOCKERFILE}\n"
        f"#   image: {spec.image}\n"
        "#   profiles: [ui]\n"
        "#   env_file: [./.env]\n"
        "#   ports:\n"
        f'#     - "{port}:{port}"\n'
        f'#   command: ["web", "--host", "0.0.0.0", "--port", "{port}"]\n'
    )


def compose_yaml(spec: ContainerSpec) -> str:
    header = (
        f"# {spec.project} - generated by hobees Studio (Containers)\n"
        "# Environment values come from .env; no secret values are written here.\n"
    )
    return header + yaml.safe_dump(compose_document(spec), sort_keys=False, allow_unicode=True) + optional_web_block(spec)


def default_spec(api_key_envs: list[str] | None = None, run_hive: str = "") -> ContainerSpec:
    """Spec built from the running settings, so Studio starts from what is live now."""
    return ContainerSpec(
        run_hive=run_hive,
        api_key_envs=[name for name in (api_key_envs or []) if name and name != "NONE"],
    )


def validate_compose(text: str) -> tuple[dict[str, Any], list[str]]:
    """Parse a compose file and report structural problems before anything is run."""
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Compose file must be a mapping with a `services:` block")

    services = parsed.get("services")
    warnings: list[str] = []
    if not isinstance(services, dict) or not services:
        warnings.append("no `services:` entries - `docker compose up` would start nothing")
        return parsed, warnings

    for name, body in services.items():
        if not isinstance(body, dict):
            warnings.append(f"service {name!r} is not a mapping")
            continue
        if not body.get("image") and not body.get("build"):
            warnings.append(f"service {name!r} has neither `image` nor `build`")
        if body.get("privileged"):
            warnings.append(f"service {name!r} requests `privileged` mode")
        env = body.get("environment") or {}
        if isinstance(env, dict):
            for key, value in env.items():
                if _SECRET_LIKE.search(str(key)) and not str(value).startswith("${"):
                    warnings.append(
                        f"service {name!r} writes {key} as a literal value; use a ${{{key}}} reference"
                    )
    return parsed, warnings


def project_root() -> Path:
    """Project directory the generated files are written to (`HOBEES_PROJECT_ROOT`)."""
    return Path(os.getenv("HOBEES_PROJECT_ROOT", Path.cwd())).resolve()


def save_project_files(files: dict[str, str], root: Path | str | None = None) -> list[Path]:
    """Write the generated files at the project root.

    Names are validated (no path separators) and every target is checked against the
    project root, so a request cannot steer a write anywhere else. Empty content is
    skipped rather than creating an empty file.
    """
    target = Path(root).resolve() if root else project_root()
    written: list[Path] = []
    for name, content in files.items():
        if not content:
            continue
        if not _FILE_NAME.match(name):
            raise ValueError(f"{name!r} cannot be written at the project root as a plain file name")
        path = target / name
        if not path.resolve().is_relative_to(target):
            raise ValueError(f"{name} cannot be written outside the project root")
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def generated_files(spec: ContainerSpec, contents: dict[str, str]) -> dict[str, str]:
    """The names the plan writes: compose, Dockerfile, config, goal (when baked), script."""
    files = {
        DEFAULT_COMPOSE_FILE: contents.get(DEFAULT_COMPOSE_FILE, ""),
        DEFAULT_DOCKERFILE: contents.get(DEFAULT_DOCKERFILE, ""),
        spec.config_file: contents.get(spec.config_file, ""),
        spec.entrypoint_file: contents.get(spec.entrypoint_file, ""),
        DEFAULT_ENV_SAMPLE_FILE: contents.get(DEFAULT_ENV_SAMPLE_FILE, ""),
    }
    if spec.goal_mode == "bake":
        files[spec.goal_file] = contents.get(spec.goal_file, "")
    return files


def docker_available() -> bool:
    return shutil.which("docker") is not None


def entrypoint_text(spec: ContainerSpec) -> str:
    """The container entrypoint: initialise with the copied config, then run the goal.

    Only paths appear in the script - the goal text stays in its own file, so a prompt
    can never be read as shell by the container. Args passed to `docker compose run`
    override the default command.
    """
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            "",
            "# The exit code is what a pipeline reads: 0 completed, 1 failed, 2 stopped for an",
            "# approval a headless run cannot answer. `set -eu` and `exec` keep it intact, so",
            "# nothing between hobees and the container exit code can swallow it.",
            "",
            'CONFIG="${HOBEES_CONFIG_PATH:-' + CONFIG_TARGET + '}"',
            'GOAL="${HOBEES_GOAL_FILE:-' + GOAL_TARGET + '}"',
            'HIVE="${HOBEES_RUN_HIVE:-}"',
            "",
            "run() {",
            '  if [ -n "$HIVE" ]; then',
            '    hobees run --hive "$HIVE" "$@"',
            "  else",
            "    hobees run \"$@\"",
            "  fi",
            "}",
            "",
            "# 1. Initialize hobees with the configuration copied into the image.",
            'if [ -f "$CONFIG" ]; then',
            '  hobees init --config "$CONFIG"',
            "fi",
            "",
            "# 2. Container args override the default command.",
            'if [ "$#" -gt 0 ]; then',
            '  exec hobees "$@"',
            "fi",
            "",
            "# 3. Run the goal: the mounted or baked file, or stdin when the pipeline pipes one.",
            'if [ -f "$GOAL" ]; then',
            '  exec run --goal-file "$GOAL" --json',
            "fi",
            "exec run - --json",
            "",
        ]
    )


def dockerfile_text(spec: ContainerSpec) -> str:
    """Mirror the repo `Dockerfile`: hobees is installed from PyPI, the source is not in the image."""
    home = "/home/hobees"
    lines = [
        f"FROM {spec.base_image}",
        "",
        "ENV PYTHONUNBUFFERED=1 \\",
        "    PYTHONDONTWRITEBYTECODE=1",
        "",
        "# 1. Install uv system-wide as root",
        "RUN pip install --no-cache-dir uv",
        "",
        "# 2. Create the non-root user and the data directories before switching users",
        "RUN groupadd --system --gid 10001 hobees \\",
        f"    && useradd --system --uid 10001 --gid hobees --home-dir {home} --create-home hobees \\",
        "    && mkdir -p /data/artifacts /data/skills /data/config \\",
        f"    && chown -R hobees:hobees /data {home}",
        "",
        "# 3. Switch to user space BEFORE running uv commands",
        "USER hobees",
        f"WORKDIR {spec.working_dir}",
        "",
        "# 4. Add the user's local bin directory to PATH",
        f'ENV PATH="{home}/.local/bin:$PATH"',
        "",
        "# 5. Install from PyPi",
        "RUN uv tool install hobees",
        "",
        "# 6. The active configuration and the entrypoint script: init, then the goal",
        f"ENV HOBEES_CONFIG_PATH={CONFIG_TARGET}",
    ]
    if spec.goal_mode != "stdin":
        # The script reads both paths from the environment, so each value is defined once -
        # here. In stdin mode there is no goal file to point at.
        lines.append(f"ENV HOBEES_GOAL_FILE={GOAL_TARGET}")
    lines += [
        f"COPY --chown={CONTAINER_USER} {spec.config_file} {CONFIG_TARGET}",
        f"COPY --chown={CONTAINER_USER} {spec.entrypoint_file} {CONTAINER_ENTRYPOINT}",
        f"RUN chmod +x {CONTAINER_ENTRYPOINT}",
    ]
    if spec.goal_mode == "bake":
        # Baking freezes the prompt into an image layer: a goal change needs a rebuild and the
        # text shows up in `docker history`. Mount (the default) keeps the image reusable.
        lines.append(f"COPY --chown={CONTAINER_USER} {spec.goal_file} {GOAL_TARGET}")
    # A baked CMD would duplicate the script: the script decides, and args passed to
    # `docker run` / `docker compose run` override it.
    lines.append("# No CMD on purpose: docker-entrypoint.sh runs init, then the goal; args override it.")
    lines.append(f'ENTRYPOINT ["{CONTAINER_ENTRYPOINT}"]')
    return "\n".join(lines) + "\n"

def env_keys_referenced(compose_text: str) -> list[str]:
    """Names the generated compose file reads from .env, in order of appearance."""
    seen: list[str] = []
    for name in re.findall(r"\$\{([A-Za-z0-9_]+)", compose_text):
        if name not in seen:
            seen.append(name)
    return seen


def env_sample_text(spec: ContainerSpec) -> str:
    """`.env.sample`: the keys the generated files need, listed without values.

    Required first (no default, the container fails without them), then the names compose
    can fall back on. No key value is written anywhere - this is a checklist for `.env`, so
    a pipeline can copy it on the host that runs the container and fill the values there.
    """
    referenced = env_keys_referenced(compose_yaml(spec))
    required = [name for name in spec.api_key_envs if name and name != "NONE"]
    if spec.include_db:
        required.append("POSTGRES_PASSWORD")
    required = sorted(set(required))
    optional = [name for name in referenced if name not in required]

    lines = [
        f"# {spec.project} - {DEFAULT_ENV_SAMPLE_FILE} (generated by hobees Studio, Containers tab)",
        "# Keys only - copy to .env and fill the values. The generated files read these names,",
        "# so a key missing here cannot be used by the container.",
        "",
        "# Required",
    ]
    for key in required:
        lines.append(f"{key}=")
    if optional:
        lines.append("")
        lines.append("# Referenced with a default in compose.yaml - set them to override")
        for key in optional:
            lines.append(f"{key}=")
    return "\n".join(lines) + "\n"

__all__ = [
    "ContainerSpec",
    "DEFAULT_BASE_IMAGE",
    "DEFAULT_COMPOSE_FILE",
    "DEFAULT_DOCKERFILE",
    "compose_document",
    "compose_yaml",
    "default_spec",
    "docker_available",
    "DEFAULT_ENV_SAMPLE_FILE",

    "validate_compose",
]
