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

The shape of every file follows the set that is known to run against Docker: `init-dirs`
creates the host folders the bind mounts point at and hands them to the container user
before anything else starts, the goal runner waits for that and for a healthy database,
and Postgres keeps its data in a project folder rather than a named volume. Values come
from the fields the Containers tab exposes as inputs; the structure around them is fixed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_BASE_IMAGE = "python:3.12-slim"
DEFAULT_COMPOSE_FILE = "compose.yaml"
DEFAULT_DOCKERFILE = "Dockerfile"
DEFAULT_ENTRYPOINT_FILE = "docker-entrypoint.sh"
DEFAULT_CONFIG_FILE = "hobees.yaml"
DEFAULT_GOAL_FILE = "goal.txt"
DEFAULT_ENV_SAMPLE_FILE = ".env.sample"

#: `hobees web` binds 6543 by default, so the container publishes the same port.
DEFAULT_HOME = "/home/hobees"
DEFAULT_WORKING_DIR = DEFAULT_HOME
DEFAULT_WEB_PORT = 6543

#: The ids baked into the image. `.env` maps the host user onto them, so a run on another
#: machine only changes .env, not the generated files.
DEFAULT_UID = 1000
DEFAULT_GID = 1000

#: Folders the image creates under the home directory, matching the default mounts.
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_SKILLS_DIR = "skills"
DEFAULT_CONFIG_DIR = "config"

#: `init-dirs` runs as root, mounts the project folder and prepares the bind-mounted
#: directories before the services that write into them start.
DEFAULT_INIT_SERVICE = "init-dirs"
DEFAULT_INIT_IMAGE = "alpine:3.20"
DEFAULT_INIT_WORKSPACE = "/workspace"

#: `docker compose run --rm` exits after the goal; a restart policy would only keep the
#: container alive and hide the exit code the pipeline reads.
DEFAULT_RESTART = "no"
DEFAULT_EXTRA_HOSTS = ["host.docker.internal:host-gateway"]

DEFAULT_DB_IMAGE = "postgres:16-alpine"
DEFAULT_DB_NAME = "hobeesdb"
DEFAULT_DB_USER = "hobees"
#: A host folder rather than a named volume, so init-dirs can create and chown it.
DEFAULT_DB_VOLUME = "./postgres_data"
DB_DATA_TARGET = "/var/lib/postgresql/data"

GOAL_MODES: tuple[str, ...] = ("mount", "bake", "stdin")
DEFAULT_GOAL_MODE = "mount"

CONTAINER_ENTRYPOINT = "/entrypoint.sh"
CONTAINER_USER = "hobees"
CONTAINER_NAME_PLACEHOLDER = "${HOBEES_CONTAINER_NAME:-hobees}"
CONTAINER_NAME_DEFAULT = "hobees"

#: Every path written into a generated file is relative to the project root or inside the
#: image - a path from the author's machine must never end up in a committed file.

_SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_FILE_NAME = re.compile(r"^\.{0,1}[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET_LIKE = re.compile(r"(?:api[_-]?key|token|secret|password|credential)", re.IGNORECASE)

#: Plain scalars a YAML loader would read as something other than a string, so the
#: generator quotes them. A port mapping such as `6543:6543` is not one of these, which is
#: why the tested file writes it plain while `"0:0"` needs quotes.
_YAML_SPECIAL = re.compile(
    r"^(?:[-+]?[0-9][0-9_]*(?:\.[0-9_]*)?(?:[eE][-+][0-9]+)?"
    r"|(?:[0-9][0-9_]*(?::[0-5]?[0-9])+)"
    r"|[-+]?\.[0-9_]+"
    r"|[-+]?[Ii]nf|[Nn]an"
    r"|0x[0-9a-fA-F_]+|0o?[0-7]+|0b[01_]+"
    r"|(?:yes|no|on|off|true|false|null|~)"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2})$",
    re.IGNORECASE,
)
_PLAIN_UNSAFE = re.compile(r"[^\x20-\x7e]")
_INDICATORS = "-?:,[]{}#&*!|>'\"`@"


class ContainerSpec(BaseModel):
    """One container definition plus the project settings it runs under."""

    project: str = "hobees"
    service: str = "hobees"
    image: str = "hobees:local"
    container_name: str = ""
    base_image: str = DEFAULT_BASE_IMAGE
    working_dir: str = DEFAULT_WORKING_DIR
    user: str = f"${{HOBEES_UID:-{DEFAULT_UID}}}:${{HOBEES_GID:-{DEFAULT_GID}}}"
    #: Empty means the image's own ENTRYPOINT (the generated script) is used.
    entrypoint: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    profiles: list[str] = Field(default_factory=lambda: ["pipeline"])
    restart: str = DEFAULT_RESTART
    ports: list[str] = Field(default_factory=lambda: [f"{DEFAULT_WEB_PORT}:{DEFAULT_WEB_PORT}"])
    volumes: list[str] = Field(default_factory=list)
    init: bool = True
    extra_hosts: list[str] = Field(default_factory=lambda: list(DEFAULT_EXTRA_HOSTS))

    # --- The folders init-dirs prepares ---
    init_service: str = DEFAULT_INIT_SERVICE
    init_image: str = DEFAULT_INIT_IMAGE
    init_workspace: str = DEFAULT_INIT_WORKSPACE
    output_dir: str = DEFAULT_OUTPUT_DIR
    skills_dir: str = DEFAULT_SKILLS_DIR

    #: Environment variables the container reads. Values stay `${NAME}` references so
    #: the generated file never contains a key.
    env: dict[str, str] = Field(default_factory=dict)
    api_key_envs: list[str] = Field(default_factory=list)

    # --- Database service ---
    include_db: bool = True
    db_image: str = DEFAULT_DB_IMAGE
    db_volume: str = DEFAULT_DB_VOLUME
    db_name: str = DEFAULT_DB_NAME
    db_user: str = DEFAULT_DB_USER
    #: The compose service key and the host name the container resolves; one value, used in both places.
    postgres_service_name: str = "postgres"
    web_service_name: str = "web"

    # --- What the container carries and runs ---
    #: The active configuration the user is happy with, exported as `hobees.yaml`.
    config_file: str = DEFAULT_CONFIG_FILE
    config_dir: str = DEFAULT_CONFIG_DIR
    #: The goal prompt and how it reaches the container: mount (default), bake, stdin.
    #: The text is stored as a file, never written into the entrypoint script.
    goal: str = ""
    goal_file: str = DEFAULT_GOAL_FILE
    goal_mode: str = DEFAULT_GOAL_MODE
    #: Hive the pipeline runs; empty means the Queen/auto mode.
    run_hive: str = ""
    #: The entrypoint script initializes the schema with the config before the goal.
    run_init: bool = True
    entrypoint_file: str = DEFAULT_ENTRYPOINT_FILE
    #: Running the web app from the container is optional: it stays commented out in
    #: the generated compose file unless the user asks for it.
    include_web: bool = False

    # --- Paths inside the image, derived from the settings above ---

    def home(self) -> str:
        return self.working_dir or DEFAULT_WORKING_DIR

    def output_target(self) -> str:
        return f"{self.home()}/{self.output_dir}"

    def skills_target(self) -> str:
        return f"{self.home()}/{self.skills_dir}"

    def config_target(self) -> str:
        return f"{self.home()}/{self.config_dir}/{self.config_file}"

    def goal_target(self) -> str:
        return f"{self.home()}/{self.goal_file}"

    def uid(self) -> int:
        match = re.search(r"\{HOBEES_UID:-(\d+)\}", self.user) or re.match(r"^(\d+):", self.user)
        return int(match.group(1)) if match else DEFAULT_UID

    def gid(self) -> int:
        match = re.search(r"\{HOBEES_GID:-(\d+)\}", self.user) or re.match(r"^\d+:(\d+)", self.user)
        return int(match.group(1)) if match else DEFAULT_GID

    def resolved_container_name(self) -> str:
        return self.container_name or CONTAINER_NAME_PLACEHOLDER

    def default_volumes(self) -> list[str]:
        """The mounts the image expects: the folders it creates under the home directory."""
        return [f"./{self.output_dir}:{self.output_target()}", f"./{self.skills_dir}:{self.skills_target()}"]

    def goal_mount(self) -> str | None:
        """Read-only goal mount - the pipeline default, so a goal can change without a rebuild."""
        if self.goal_mode != "mount":
            return None
        return f"./{self.goal_file}:{self.goal_target()}:ro"

    def resolved_volumes(self) -> list[str]:
        mounts = list(self.volumes) or self.default_volumes()
        goal = self.goal_mount()
        if goal and goal not in mounts:
            mounts.append(goal)
        return mounts

    def host_dirs(self) -> list[str]:
        """Host folders the generated compose file bind-mounts, in the order they appear."""
        dirs: list[str] = []
        for mount in self.volumes or self.default_volumes():
            host = mount.split(":", 1)[0]
            if not host.startswith("./"):
                continue  # a named volume or an absolute host path is not prepared here
            if host == f"./{self.goal_file}":
                continue  # the goal is a file, not a folder init-dirs can create
            name = (host[2:].split("/")[0] or ".").strip()
            if name and name not in dirs:
                dirs.append(name)
        if self.include_db and self.db_volume.startswith("./"):
            name = (self.db_volume[2:].split("/")[0] or ".").strip()
            if name and name not in dirs:
                dirs.append(name)
        return dirs

    def db_url(self) -> str:
        return (
            "postgresql+psycopg://"
            f"${{POSTGRES_USER:-{self.db_user}}}:${{POSTGRES_PASSWORD:?error}}"
            f"@{self.postgres_service_name}:5432/${{POSTGRES_DB:-{self.db_name}}}"
        )

    def resolved_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if self.include_db:
            env["HOBEES_DATABASE_URL"] = self.db_url()
        # The runtime paths and the hive are read from .env by the entrypoint script, so
        # they are not redefined here: .env.sample carries them.
        for key, value in self.env.items():
            env[key] = value
        for name in self.api_key_envs:
            if name and name != "NONE":
                env.setdefault(name, f"${{{name}}}")
        return env

    def pipeline_command(self) -> list[str]:
        """What the entrypoint script runs. Shown so CI can mirror it - it is not baked as
        `CMD`, because the script is the single place that decides what happens."""
        args = ["run"]
        if self.run_hive:
            args.extend(["--hive", self.run_hive])
        if self.goal_mode in ("mount", "bake"):
            # Only the path appears here, never the prompt: the goal stays data.
            args.extend(["--json", '"$(cat ' + self.goal_target() + ')"'])
        else:
            args.extend(["-", "--json"])
        return args

    def resolved_command(self) -> list[str]:
        """An explicit override only. Left empty, the entrypoint script's own default runs."""
        return list(self.command)

    def warnings(self) -> list[str]:
        notes: list[str] = []
        if not _SERVICE_NAME.match(self.service):
            notes.append(f"service name {self.service!r} is not a valid compose service key")
        if not self.profiles:
            notes.append(
                "no profiles set: `docker compose run --rm <service>` starts this service "
                "without the `--profile` flag the run command shows"
            )
        if self.goal_mode not in GOAL_MODES:
            notes.append(f"goal_mode {self.goal_mode!r} must be one of {', '.join(GOAL_MODES)}")
        for name in (self.config_file, self.goal_file, self.entrypoint_file):
            if not _FILE_NAME.match(name):
                notes.append(f"file name {name!r} cannot be written at the project root")
        if not self.goal.strip():
            notes.append(
                "no goal set: the container would start with nothing to run - pipe one "
                "(`docker compose --profile <profile> run -T --rm <service>`) or fill the goal field"
            )
        for key, value in self.resolved_env().items():
            if _SECRET_LIKE.search(key) and not str(value).startswith("${"):
                notes.append(f"{key} is written as a literal value; use a ${{{key}}} reference instead")
        for mount in self.resolved_volumes():
            host = mount.split(":", 1)[0]
            if "/" in host and not host.startswith("./"):
                notes.append(
                    f"volume {mount!r} points at an absolute host path; a generated file should "
                    "stay relative to the project root so init-dirs can prepare it"
                )
        return notes


def yaml_scalar(value: Any) -> str:
    """A scalar written the way the tested compose file writes it: plain when a loader
    reads it as a string, double-quoted when it would read a number, a bool or null."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    text = str(value)
    if not text or text != text.strip():
        return json.dumps(text)
    first = text[0]
    # `-`, `?` and `:` only start a node when a space follows them, so `-c` stays plain.
    if first in _INDICATORS and not (first in "-?:" and len(text) > 1 and text[1] != " "):
        return json.dumps(text)
    if _PLAIN_UNSAFE.search(text) or "\n" in text:
        return json.dumps(text)
    if ": " in text or " #" in text or text.endswith((":", "#")) or _YAML_SPECIAL.match(text):
        return json.dumps(text)
    return text


def _dump(node: Any, indent: int) -> list[str]:
    """Render one block of the compose document at the given indentation."""
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.extend(_dump(value, indent + 1))
            elif isinstance(value, dict):
                lines.append(f"{pad}{key}: {{}}")
            elif isinstance(value, list):
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(value)}")
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, str) and "\n" in item:
                # The init-dirs command is kept as a literal block: two shell lines, no quoting.
                lines.append(f"{pad}- |")
                for line in item.split("\n"):
                    lines.append(f"{'  ' * (indent + 1)}{line}")
            elif isinstance(item, dict) and item:
                sub = _dump(item, indent + 1)
                lines.append(f"{pad}- {sub[0].strip()}")
                lines.extend(sub[1:])
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
    return lines


def compose_document(spec: ContainerSpec) -> dict[str, Any]:
    """The services, in the order the tested file writes them: init-dirs, the runner, Postgres."""
    document: dict[str, Any] = {}
    dirs = spec.host_dirs()

    if dirs:
        block = " ".join(f"{spec.init_workspace}/{name}" for name in dirs)
        document[spec.init_service] = {
            "image": spec.init_image,
            "user": "0:0",
            "volumes": [f".:{spec.init_workspace}"],
            "command": ["sh", "-c", f"mkdir -p {block} &&\nchown -R {spec.user} {block}"],
        }

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
        "init": spec.init,
    }
    if spec.profiles:
        service["profiles"] = spec.profiles
    if spec.extra_hosts:
        service["extra_hosts"] = list(spec.extra_hosts)
    if spec.ports:
        service["ports"] = spec.ports
    if spec.restart:
        service["restart"] = spec.restart
    # Only an override the user typed is written: the entrypoint script already runs
    # init then the goal, so a default `command` would duplicate that decision.
    if spec.command:
        service["command"] = list(spec.command)
    if spec.entrypoint:
        service["entrypoint"] = list(spec.entrypoint)

    depends: dict[str, Any] = {}
    if dirs:
        depends[spec.init_service] = {"condition": "service_completed_successfully"}
    if spec.include_db:
        depends[spec.postgres_service_name] = {"condition": "service_healthy"}
    if depends:
        service["depends_on"] = depends
    document[spec.service] = service

    if spec.include_db:
        database: dict[str, Any] = {
            "image": spec.db_image,
            "env_file": ["./.env"],
            # A project folder, not a named volume, so init-dirs can create it first.
            "volumes": [f"{spec.db_volume}:{DB_DATA_TARGET}"],
        }
        if dirs:
            database["depends_on"] = {spec.init_service: {"condition": "service_completed_successfully"}}
        database["healthcheck"] = {
            "test": [
                "CMD-SHELL",
                'pg_isready -U "$${POSTGRES_USER:-' + spec.db_user + '}" -d "$${POSTGRES_DB:-' + spec.db_name + '}"',
            ],
            "interval": "5s",
            "timeout": "5s",
            "retries": 10,
            "start_period": "5s",
        }
        document[spec.postgres_service_name] = database

    if spec.include_web:
        # Only when asked for: a pipeline does not need the web app running in the container.
        document[spec.web_service_name] = {
            "build": {"context": ".", "dockerfile": "./" + DEFAULT_DOCKERFILE},
            "image": spec.image,
            "profiles": ["ui"],
            "env_file": ["./.env"],
            "ports": [f"{DEFAULT_WEB_PORT}:{DEFAULT_WEB_PORT}"],
            "command": ["web", "--host", "0.0.0.0", "--port", str(DEFAULT_WEB_PORT)],
        }

    return document


def compose_header(spec: ContainerSpec) -> str:
    return (
        f"# {spec.project} - generated by hobees Studio (Containers)\n"
        "# Environment values come from .env; no secret values are written here.\n"
    )


def compose_yaml(spec: ContainerSpec) -> str:
    """The compose file, rendered in the shape of the set that is known to run."""
    lines = [compose_header(spec).rstrip("\n"), "services:"]
    for index, (name, body) in enumerate(compose_document(spec).items()):
        if index:
            lines.append("")
        lines.append(f"  {name}:")
        lines.extend(_dump(body, 2))
    return "\n".join(lines) + "\n" + optional_web_block(spec) + "\n"


def optional_web_block(spec: ContainerSpec) -> str:
    """The commented-out web service - running the web app in the container is optional."""
    if spec.include_web:
        return ""
    port = DEFAULT_WEB_PORT
    return (
        "\n# Optional: the web app is not needed to run a goal, so this stays commented out.\n"
        f"#   {spec.web_service_name}:\n"
        "#     build:\n"
        "#       context: .\n"
        f"#       dockerfile: ./{DEFAULT_DOCKERFILE}\n"
        f"#     image: {spec.image}\n"
        "#     profiles: [ui]\n"
        "#     env_file: [./.env]\n"
        "#     ports:\n"
        f'#       - "{port}:{port}"\n'
        f'#     command: ["web", "--host", "0.0.0.0", "--port", "{port}"]'
    )


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
    skipped rather than creating an empty file. Files are written with LF endings: a
    `docker-entrypoint.sh` saved with CRLF fails inside the container (`#!/bin/sh\r` is read
    as a bad interpreter), whatever system wrote it.
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
        path.write_text(content, encoding="utf-8", newline="\n")
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
    home = spec.home()
    lines = [
        "#!/bin/sh",
        "set -eu",
        "",
        "# The exit code is what a pipeline reads: 0 completed, 1 failed, 2 stopped for an",
        "# approval a headless run cannot answer. `set -eu` and `exec` keep it intact, so",
        "# nothing between hobees and the container exit code can swallow it.",
        "",
        'HOME_DIR="${HOME:-' + home + '}"',
        'CONFIG="${HOBEES_CONFIG_PATH:-${HOME_DIR}/' + f'{spec.config_dir}/{spec.config_file}' + '}"',
        'GOAL="${HOBEES_GOAL_FILE:-${HOME_DIR}/' + f'{spec.goal_file}' + '}"',
        'HIVE="${HOBEES_RUN_HIVE:-}"',
        "",
    ]

    sections: list[tuple[str, list[str]]] = []
    if spec.run_init:
        sections.append(
            (
                "Initialize hobees with the configuration copied into the image.",
                ['if [ -f "$CONFIG" ]; then', '  hobees init --config "$CONFIG"', "fi"],
            )
        )
    sections.append(
        ("Container args override the default command.", ['if [ "$#" -gt 0 ]; then', '  exec hobees "$@"', "fi"])
    )
    sections.append(
        (
            "Build positional arguments for `hobees run` (dash-compatible, no bash arrays).",
            ["set --", 'if [ -n "$HIVE" ]; then', '  set -- --hive "$HIVE"', "fi"],
        )
    )
    if spec.goal_mode == "stdin":
        # No file to read, so the pipe is the only source.
        sections.append(("Read the goal from stdin.", ['exec hobees run "$@" - --json']))
    else:
        sections.append(
            (
                "Run the goal from file if mounted; otherwise read from stdin.",
                [
                    'if [ -f "$GOAL" ]; then',
                    '  exec hobees run "$@" --json "$(cat "$GOAL")"',
                    "fi",
                    'exec hobees run "$@" - --json',
                ],
            )
        )

    for number, (comment, body) in enumerate(sections, start=1):
        if number > 1:
            lines.append("")
        lines.append(f"# {number}. {comment}")
        lines.extend(body)
    return "\n".join(lines) + "\n"


def dockerfile_text(spec: ContainerSpec) -> str:
    """Mirror the repo `Dockerfile`: hobees is installed from PyPI, the source is not in the image."""
    home = spec.home()
    lines = [
        f"FROM {spec.base_image}",
        "",
        "ENV PYTHONUNBUFFERED=1 \\",
        "    PYTHONDONTWRITEBYTECODE=1 \\",
        f"    HOME={home} \\",
        "    UV_TOOL_DIR=/opt/uv-tools \\",
        "    UV_TOOL_BIN_DIR=/usr/local/bin",
        "",
        "# 1. Install uv system-wide as root",
        "RUN pip install --no-cache-dir uv",
        "",
        "# 2. Create non-root user and directories",
        f"RUN groupadd --system --gid {spec.gid()} hobees \\",
        f"    && useradd --system --uid {spec.uid()} --gid hobees --home-dir ${{HOME}} --create-home hobees \\",
        f"    && mkdir -p ${{HOME}}/{spec.output_dir} ${{HOME}}/{spec.skills_dir} ${{HOME}}/{spec.config_dir} /opt/uv-tools \\",
        f"    && chown -R {CONTAINER_USER}:hobees ${{HOME}} /opt/uv-tools",
        "",
        "# 3. Install hobees into /opt/uv-tools with symlink in /usr/local/bin",
        "RUN uv tool install hobees && chmod -R a+rX /opt/uv-tools ${HOME}",
        "",
        "# 4. Copy default config and entrypoint",
        f"COPY --chown={CONTAINER_USER}:hobees {spec.config_file} ${{HOME}}/{spec.config_dir}/{spec.config_file}",
        f"COPY --chown={CONTAINER_USER}:hobees {spec.entrypoint_file} {CONTAINER_ENTRYPOINT}",
        f"RUN chmod +x {CONTAINER_ENTRYPOINT}",
    ]
    if spec.goal_mode == "bake":
        # Baking freezes the prompt into an image layer: a goal change needs a rebuild and the
        # text shows up in `docker history`. Mount (the default) keeps the image reusable.
        lines += [
            "",
            f"# 5. Bake the goal ({spec.goal_file}) - in mount mode it stays a host file instead",
            f"COPY --chown={CONTAINER_USER}:hobees {spec.goal_file} ${{HOME}}/{spec.goal_file}",
        ]
    # A baked CMD would duplicate the script: the script decides, and args passed to
    # `docker run` / `docker compose run` override it.
    lines += [
        "",
        f"USER {CONTAINER_USER}",
        "WORKDIR ${HOME}",
        "",
        f'ENTRYPOINT ["{CONTAINER_ENTRYPOINT}"]',
    ]
    return "\n".join(lines) + "\n"


def env_keys_referenced(compose_text: str) -> list[str]:
    """Names the generated compose file reads from .env, in order of appearance."""
    seen: list[str] = []
    for name in re.findall(r"\$\{([A-Za-z0-9_]+)", compose_text):
        if name not in seen:
            seen.append(name)
    return seen


def env_sample_text(spec: ContainerSpec) -> str:
    """`.env.sample`: the keys the generated files need, in the order `.env` carries them.

    Required first (no default, the container fails without them), then the names compose
    can fall back on. No key value is written anywhere - this is a checklist for `.env`, so
    a pipeline can copy it on the host that runs the container and fill the values there.
    """
    referenced = env_keys_referenced(compose_yaml(spec))
    required = sorted({name for name in spec.api_key_envs if name and name != "NONE"} | ({"POSTGRES_PASSWORD"} if spec.include_db else set()))
    written: set[str] = set()

    lines = [
        f"# {spec.project} - {DEFAULT_ENV_SAMPLE_FILE} (generated by hobees Studio, Containers tab)",
        "# Keys only - copy to .env and fill the values. The generated files read these names,",
        "# so a key missing here cannot be used by the container.",
        "",
        "# Host UID/GID mapping",
        f"HOBEES_UID={spec.uid()}",
        f"HOBEES_GID={spec.gid()}",
    ]
    written.update({"HOBEES_UID", "HOBEES_GID"})

    if spec.include_db:
        lines += [
            "",
            "# Postgres credentials",
            f"POSTGRES_DB={spec.db_name}",
            f"POSTGRES_USER={spec.db_user}",
            "POSTGRES_PASSWORD=",  # required, no default: the value stays on the host
        ]
        written.update({"POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"})

    if spec.api_key_envs:
        lines += ["", "# Provider API keys (the names come from the Providers tab; no key is written)"]
        for key in sorted({name for name in spec.api_key_envs if name and name != "NONE"}):
            lines.append(f"{key}=")
            written.add(key)

    lines += [
        "",
        "# Hobees runtime configuration",
        f"HOBEES_RUN_HIVE={spec.run_hive}" if spec.run_hive else "HOBEES_RUN_HIVE=",  # empty = Queen auto-mode
        f"HOBEES_ARTIFACTS_ROOT={spec.output_target()}",
        f"HOBEES_SKILLS_DIR={spec.skills_target()}",
        f"HOBEES_CONFIG_PATH={spec.config_target()}",
        f"HOBEES_GOAL_FILE={spec.goal_target()}"
        + ("  # stdin mode: the goal is piped, this path is only a fallback" if spec.goal_mode == "stdin" else ""),
    ]
    written.update({"HOBEES_RUN_HIVE", "HOBEES_ARTIFACTS_ROOT", "HOBEES_SKILLS_DIR", "HOBEES_CONFIG_PATH", "HOBEES_GOAL_FILE"})
    if not spec.container_name:
        lines.append(f"HOBEES_CONTAINER_NAME={CONTAINER_NAME_DEFAULT}")
        written.add("HOBEES_CONTAINER_NAME")

    extra = [name for name in referenced if name not in written]
    if extra:
        lines += ["", "# Other names the generated compose file reads, with the defaults shown above"]
        for key in extra:
            lines.append(f"{key}=")

    return "\n".join(lines) + "\n"


__all__ = [
    "ContainerSpec",
    "DEFAULT_BASE_IMAGE",
    "DEFAULT_COMPOSE_FILE",
    "DEFAULT_DOCKERFILE",
    "DEFAULT_ENTRYPOINT_FILE",
    "DEFAULT_ENV_SAMPLE_FILE",
    "DEFAULT_GOAL_FILE",
    "GOAL_MODES",
    "compose_document",
    "compose_header",
    "compose_yaml",
    "default_spec",
    "docker_available",
    "dockerfile_text",
    "entrypoint_text",
    "env_keys_referenced",
    "env_sample_text",
    "generated_files",
    "optional_web_block",
    "project_root",
    "save_project_files",
    "validate_compose",
    "yaml_scalar",
]
