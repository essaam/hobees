"""How a pipeline learns the outcome of a short-lived container run.

Two signals, used in this order by a pipeline manager:

1. **The exit code.** `docker run` and `docker compose run` return the container's exit
   code, and that stays true when the container runs against a remote daemon
   (`docker -H ssh://host`, `DOCKER_HOST`), so the shell or CI step sees it directly.
   Nothing is added to the `Dockerfile` for this: hobees' own exit code is already the
   container's exit code. The generated `docker-entrypoint.sh` keeps that path intact by
   using `set -eu` (a failing `hobees init` stops the script with that code) and `exec`
   (the final command replaces the shell, so its code is reported unchanged).
   For a detached run the code is read back with `docker inspect -f '{{.State.ExitCode}}'`
   or `docker compose up --exit-code-from <service>`.
2. **The run manifest.** The exit code says *how* it ended; the manifest written into the
   artifacts mount says *what happened* - status, error, usage - and survives on the
   pipeline host even when the container is gone.

Exit codes: 0 completed, 1 failed, 2 stopped for an approval a headless run cannot answer,
3 still running (a status lookup that has not reached a terminal state).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_AWAITING_APPROVAL = 2
EXIT_RUNNING = 3

STATUS_EXIT_CODES: dict[str, int] = {
    "completed": EXIT_COMPLETED,
    "failed": EXIT_FAILED,
    "awaiting_approval": EXIT_AWAITING_APPROVAL,
    "running": EXIT_RUNNING,
}

#: Statuses a pipeline can act on; anything else is still in flight.
TERMINAL_STATUSES: frozenset[str] = frozenset(STATUS_EXIT_CODES) - {"running"}

MANIFEST_NAME = "run_manifest.json"


def pipeline_exit_code(status: str | None) -> int:
    """Map a run status to the exit code a pipeline should see."""
    if status is None:
        return EXIT_FAILED
    return STATUS_EXIT_CODES.get(status, EXIT_FAILED)


def is_terminal(status: str | None) -> bool:
    return status in TERMINAL_STATUSES


def manifest_entry(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    """The run the manifest describes: `last_run`, or the newest entry in `runs`."""
    if not manifest:
        return None
    if isinstance(manifest.get("last_run"), dict):
        return manifest["last_run"]
    runs = manifest.get("runs")
    if isinstance(runs, list) and runs and isinstance(runs[0], dict):
        return runs[0]
    return manifest


def read_manifest(path: Path | str) -> dict[str, Any] | None:
    """Read a manifest written by a run, or return None when it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def manifest_path_for(hive_name: str, artifacts_root: Path | str) -> Path:
    return Path(artifacts_root) / hive_name / MANIFEST_NAME


__all__ = [
    "EXIT_AWAITING_APPROVAL",
    "EXIT_COMPLETED",
    "EXIT_FAILED",
    "EXIT_RUNNING",
    "MANIFEST_NAME",
    "STATUS_EXIT_CODES",
    "TERMINAL_STATUSES",
    "is_terminal",
    "manifest_entry",
    "manifest_path_for",
    "pipeline_exit_code",
    "read_manifest",
]
