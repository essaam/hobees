"""Container preparation: compose/Dockerfile generation and guarded lifecycle actions.

This is the deployment side of Studio: the generated files carry environment-variable
*names*, never secret values, and the spin-up path only runs allowlisted
`docker compose` subcommands with fixed arguments (no shell, no arbitrary args).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from hobees.config import settings
from hobees.core.approval import resolve_container_name

#: The only subcommands the web layer may run. A fixed allowlist means a request
#: can never reach an arbitrary `docker` invocation.
ALLOWED_ACTIONS: tuple[str, ...] = ("up", "down", "ps", "logs")

DEFAULT_BASE_IMAGE = "python:3.12-slim"
DEFAULT_COMPOSE_FILE = "compose.yaml"
DEFAULT_DOCKERFILE = "Dockerfile"

_SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SECRET_LIKE = re.compile(r"(?:api[_-]?key|token|secret|password|credential)", re.IGNORECASE)


class ContainerSpec(BaseModel):
    """One container definition plus the project settings it runs under."""

    project: str = "hobees"
    service: str = "hobees"
    image: str = "hobees:local"
    container_name: str = ""
    base_image: str = DEFAULT_BASE_IMAGE
    working_dir: str = "/app"
    user: str = "${HOBEES_UID:-1000}:${HOBEES_GID:-1000}"
    entrypoint: list[str] = Field(default_factory=lambda: ["hobees"])
    command: list[str] = Field(default_factory=lambda: ["web", "--host", "0.0.0.0", "--port", "8420"])
    profiles: list[str] = Field(default_factory=lambda: ["runtime_only"])
    restart: str = "unless-stopped"
    ports: list[str] = Field(default_factory=lambda: ["8420:8420"])
    volumes: list[str] = Field(default_factory=list)
    #: Environment variables the container reads. Values stay `${NAME}` references so
    #: the generated file never contains a key.
    env: dict[str, str] = Field(default_factory=dict)
    api_key_envs: list[str] = Field(default_factory=list)
    include_db: bool = True
    db_image: str = "postgres:16-alpine"
    db_volume: str = "postgres_data"

    def resolved_container_name(self) -> str:
        return self.container_name or resolve_container_name()

    def resolved_volumes(self) -> list[str]:
        if self.volumes:
            return list(self.volumes)
        return ["./artifacts:/data/artifacts", "./skills:/data/skills"]

    def resolved_env(self) -> dict[str, str]:
        env = dict(self.env)
        env.setdefault("HOBEES_ARTIFACTS_ROOT", "/data/artifacts")
        env.setdefault("HOBEES_SKILLS_DIR", "/data/skills")
        env.setdefault("HOBEES_CONTAINER_NAME", self.resolved_container_name())
        if self.include_db:
            env.setdefault(
                "HOBEES_DATABASE_URL",
                "postgresql+psycopg://${POSTGRES_USER:-hobees}:${POSTGRES_PASSWORD}"
                "@db:5432/${POSTGRES_DB:-hobees}",
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
        for key, value in self.resolved_env().items():
            if _SECRET_LIKE.search(key) and not str(value).startswith("${"):
                notes.append(f"{key} is written as a literal value; use a ${{{key}}} reference instead")
        return notes


def compose_document(spec: ContainerSpec) -> dict[str, Any]:
    service: dict[str, Any] = {
        "build": {"context": ".", "dockerfile": DEFAULT_DOCKERFILE},
        "image": spec.image,
        "container_name": spec.resolved_container_name(),
        "user": spec.user,
        "working_dir": spec.working_dir,
        "env_file": [".env"],
        "environment": spec.resolved_env(),
        "volumes": spec.resolved_volumes(),
        "entrypoint": spec.entrypoint,
        "command": spec.command,
        "init": True,
    }
    if spec.profiles:
        service["profiles"] = spec.profiles
    if spec.ports:
        service["ports"] = spec.ports
    if spec.restart:
        service["restart"] = spec.restart

    document: dict[str, Any] = {"services": {spec.service: service}}

    if spec.include_db:
        document["services"]["db"] = {
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
        service["depends_on"] = {"db": {"condition": "service_healthy"}}
        document["volumes"] = {spec.db_volume: None}

    return document


def compose_yaml(spec: ContainerSpec) -> str:
    header = (
        f"# {spec.project} - generated by hobees Studio (Containers)\n"
        "# Environment values come from .env; no secret values are written here.\n"
    )
    return header + yaml.safe_dump(compose_document(spec), sort_keys=False, allow_unicode=True)


def default_spec(api_key_envs: list[str] | None = None) -> ContainerSpec:
    """Spec built from the running settings, so Studio starts from what is live now."""
    root = Path(settings.artifacts_root)
    skills = Path(settings.skills_dir)
    return ContainerSpec(
        container_name=resolve_container_name(),
        volumes=[f"./{root.as_posix()}:/data/artifacts", f"./{skills.as_posix()}:/data/skills"],
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


def save_project_files(compose_text: str, dockerfile: str, root: Path | str | None = None) -> list[Path]:
    """Write `compose.yaml` and `Dockerfile` at the project root.

    The file names are fixed, so a request cannot steer the write anywhere else.
    """
    target = Path(root).resolve() if root else project_root()
    written: list[Path] = []
    for name, content in ((DEFAULT_COMPOSE_FILE, compose_text), (DEFAULT_DOCKERFILE, dockerfile)):
        path = target / name
        if not path.resolve().is_relative_to(target):
            raise ValueError(f"{name} cannot be written outside the project root")
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def docker_available() -> bool:
    return shutil.which("docker") is not None


def compose_command(
    action: str,
    *,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    service: str | None = None,
    detach: bool = True,
    tail: int | None = None,
) -> list[str]:
    """Fixed, allowlisted `docker compose` argv - never a shell string."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ALLOWED_ACTIONS)}")
    argv = ["docker", "compose", "-f", compose_file, action]
    if action == "up" and detach:
        argv.append("-d")
    if action == "logs":
        argv.extend(["--tail", str(tail if tail is not None else 50)])
    if service:
        argv.append(service)
    return argv


def run_compose(
    action: str,
    project_dir: Path | str,
    *,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    service: str | None = None,
    detach: bool = True,
    tail: int | None = None,
    timeout: int = 120,
) -> str:
    if not docker_available():
        raise ValueError("docker is not available on this host")
    root = Path(project_dir).resolve()
    argv = compose_command(action, compose_file=compose_file, service=service, detach=detach, tail=tail)
    result = subprocess.run(
        argv,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"docker compose {action} failed")
    return output


def dockerfile_text(spec: ContainerSpec) -> str:
    lines = [
        f"FROM {spec.base_image}",
        "ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1",
        f"WORKDIR {spec.working_dir}",
        "RUN pip install --no-cache-dir uv",
        "COPY pyproject.toml README.md ./",
        "RUN uv sync --no-dev",
        "COPY src ./src",
        "RUN groupadd --system --gid 10001 hobees \\",
        "    && useradd --system --uid 10001 --gid hobees --home-dir /home/hobees --create-home hobees \\",
        "    && mkdir -p /data/artifacts /data/skills",
        "    && chown -R hobees:hobees /data /home/hobees",
        "USER hobees",
    ]
    if spec.entrypoint:
        lines.append("ENTRYPOINT [" + ", ".join(f'"{part}"' for part in spec.entrypoint) + "]")
    if spec.command:
        lines.append("CMD [" + ", ".join(f'"{part}"' for part in spec.command) + "]")
    return "\n".join(lines) + "\n"


__all__ = [
    "ALLOWED_ACTIONS",
    "ContainerSpec",
    "DEFAULT_BASE_IMAGE",
    "DEFAULT_COMPOSE_FILE",
    "DEFAULT_DOCKERFILE",
    "compose_command",
    "compose_document",
    "compose_yaml",
    "default_spec",
    "docker_available",
    "dockerfile_text",
    "run_compose",
    "validate_compose",
]
