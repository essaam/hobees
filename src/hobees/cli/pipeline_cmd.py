"""`hobees pipeline status` - the outcome of a run, for a pipeline manager.

A container that runs a goal is short lived: it exits as soon as the goal is done, and
`docker run` / `docker compose run` hand that exit code back to the caller - including
when the container ran against a remote daemon. That is the primary signal, and the
entrypoint script does not interfere with it (`set -eu`, then `exec`).

This command is the second, richer signal: it reads what the run left behind (the run
manifest in the artifacts mount, or the row in the database) and reports status, error and
the exit code the pipeline should use. With `--poll`, it waits for a terminal state, which
is what a pipeline needs when the run happens on another host and the artifact mount is
shared.

Exit codes: 0 completed, 1 failed, 2 stopped for an approval, 3 still running.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from hobees.cli.icons import APP, ERROR, SUCCESS, WARN
from hobees.core.pipeline_status import (
    is_terminal,
    manifest_entry,
    manifest_path_for,
    pipeline_exit_code,
    read_manifest,
)

console = Console()

app = typer.Typer(name="pipeline", help="Pipeline-facing run status (for CI and job steps)")


def _status_from_db(thread_id: str) -> dict | None:
    from hobees.db.session import session_scope
    from hobees.db.models import Run

    with session_scope() as session:
        run = session.query(Run).filter(Run.thread_id == thread_id).first()
        if not run:
            return None
        return {
            "run_id": run.id,
            "thread_id": run.thread_id,
            "status": run.status,
            "goal": run.goal,
            "artifacts_dir": run.artifacts_dir,
        }


def _resolve_entry(hive: str | None, thread_id: str | None, manifest: str | None) -> dict | None:
    from hobees.config import settings

    if manifest:
        entry = manifest_entry(read_manifest(Path(manifest)))
        if entry:
            return entry
    if hive:
        entry = manifest_entry(read_manifest(manifest_path_for(hive, settings.artifacts_root)))
        if entry:
            return entry
    if thread_id:
        return _status_from_db(thread_id)
    if hive:
        # A manifest may exist for the hive but not yet be readable; fall back to the DB.
        from hobees.db.session import session_scope
        from hobees.db.models import Hive, Run

        with session_scope() as session:
            row = (
                session.query(Run)
                .join(Hive, Run.hive_id == Hive.id)
                .filter(Hive.name == hive)
                .order_by(Run.started_at.desc())
                .first()
            )
            if not row:
                return None
            return {
                "run_id": row.id,
                "thread_id": row.thread_id,
                "status": row.status,
                "goal": row.goal,
                "artifacts_dir": row.artifacts_dir,
            }
    return None


def cmd_pipeline_status(
    hive: str | None = None,
    thread_id: str | None = None,
    manifest: str | None = None,
    output_json: bool = False,
    poll: int | None = None,
    timeout: int | None = None,
) -> int:
    """Read the run outcome and return the exit code a pipeline should use."""
    deadline = time.monotonic() + (timeout or 0)
    entry = None

    while True:
        entry = _resolve_entry(hive, thread_id, manifest)
        if entry is None:
            break
        status = str(entry.get("status") or "")
        if is_terminal(status) or not poll or time.monotonic() >= deadline:
            break
        time.sleep(min(poll, max(0.1, deadline - time.monotonic())))

    if entry is None:
        console.print(
            f"{ERROR} No run found - give --hive, --thread-id or --manifest, "
            "and make sure the run wrote its manifest."
        )
        return 1

    status = str(entry.get("status") or "running")
    code = pipeline_exit_code(status)

    if output_json:
        payload = dict(entry)
        payload["exit_code"] = code
        console.print(json.dumps(payload, indent=2), markup=False)
    else:
        mark = SUCCESS if code == 0 else (WARN if status == "running" else ERROR)
        console.print(f"{mark} status: {status} ({APP} exit code: {code})")
        if entry.get("error"):
            console.print(f"{ERROR} error: {entry['error']}")
        if entry.get("thread_id"):
            console.print(f"[dim]thread: {entry['thread_id']}[/dim]")
        if entry.get("artifacts_dir"):
            console.print(f"[dim]artifacts: {entry['artifacts_dir']}[/dim]")
        if not is_terminal(status) and poll:
            console.print(f"{WARN} not terminal after the wait window - the pipeline decides what to do")
        # A remote pipeline can read this line straight from the container output.
        console.print(f"[dim]remote equivalent: docker inspect -f '{{{{.State.ExitCode}}}}' <container>[/dim]")

    return code


@app.command(name="status")
def pipeline_status(
    hive: Annotated[str | None, typer.Option("--hive", help="Hive whose run manifest to read")] = None,
    thread_id: Annotated[str | None, typer.Option("--thread-id", help="Run thread id (DB lookup)")] = None,
    manifest: Annotated[str | None, typer.Option("--manifest", help="Path to a run_manifest.json")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Print as JSON")] = False,
    poll: Annotated[int | None, typer.Option("--poll", help="Seconds between reads while waiting for a terminal status")] = None,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Seconds to keep polling before returning")] = None,
) -> None:
    """Report how a run ended and exit with the matching code (0 done, 1 failed, 2 approval, 3 running)."""
    raise typer.Exit(
        code=cmd_pipeline_status(
            hive=hive,
            thread_id=thread_id,
            manifest=manifest,
            output_json=output_json,
            poll=poll,
            timeout=timeout,
        )
    )


__all__ = ["app", "cmd_pipeline_status"]
