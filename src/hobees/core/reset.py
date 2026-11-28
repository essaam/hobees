"""Clean the hobees slate — the files hobees created inside its own config folder.

Shared by the headless CLI (`hobees reset`) and the Studio panel in the web app.
Both front-ends confirm with the user before anything is removed, and this module
only ever deletes paths inside the plan it built.

Two scopes:

* **config** (plain `hobees reset`) — the env file, the databases and the folders
  hobees created inside `~/.hobees`: `.env`, `.detected`, `hobees.db*`, `sessions/`.
* **output** (`hobees reset --all`) — the config scope plus the generated work:
  the skills library, the scratchpad offload cache and the artifacts root.

Nothing outside that boundary is touched. Environment variables in the user's
shell are never modified — only the env file hobees wrote inside `~/.hobees` is
removed, so a provider API key exported elsewhere survives. A database configured
outside `~/.hobees` (e.g. PostgreSQL) is not dropped; only its URL goes with the
env file, and the plan reports that as a note instead of a target.

After a reset the next launch rebuilds the slate: provider detection runs again,
the default env file and database are recreated, and `hobees init` ensures the
schema.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import make_url

from hobees.config import config_dir, get_default_database_path, settings

__all__ = [
    "ResetPlan",
    "ResetResult",
    "ResetTarget",
    "build_plan",
    "apply_plan",
    "allowed_roots",
    "configured_database_file",
    "LOCKED_DATABASE_HINT",
]

#: A target is either config state or generated output. `--all` adds the output scope.
TargetGroup = Literal["config", "output"]

#: Config files and folders hobees creates inside `~/.hobees` (relative to the
#: config folder). `.env` and `hobees.db` are written by `hobees init` and the
#: shell; `sessions/` by `/session`; `.detected` by first-launch detection.
CONFIG_ITEMS: tuple[tuple[str, str], ...] = (
    (".env", "hobees env file (database URL, approval mode)"),
    (".detected", "first-launch provider detection sentinel"),
    ("sessions", "saved sessions"),
)

#: Generated output, removed only for the full scope (`--all`).
OUTPUT_ITEMS: tuple[tuple[str, str], ...] = (
    ("scratchpad", "scratchpad cache (offloaded tool output)"),
    ("artifacts", "artifacts inside ~/.hobees (run traces)"),
)

#: Files SQLite can leave beside its database file.
SQLITE_COMPANIONS: tuple[str, ...] = ("", "-journal", "-wal", "-shm")

#: Shown when a target cannot be removed because another process still has it open
#: (Windows refuses to delete a file with an active handle).
LOCKED_DATABASE_HINT = "could not be removed, still held open by another process — stop the running web app or terminal and run reset again"


@dataclass(frozen=True)
class ResetTarget:
    """One existing path that a reset would remove."""

    path: Path
    kind: Literal["file", "directory"]
    group: TargetGroup
    label: str
    entries: int = 0
    size_bytes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "group": self.group,
            "label": self.label,
            "entries": self.entries,
            "size": self.size_bytes,
        }


@dataclass
class ResetPlan:
    """What a reset would remove, as it exists on disk right now."""

    include_artifacts: bool = False
    config_dir: Path = field(default_factory=config_dir)
    targets: list[ResetTarget] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, target: ResetTarget | None) -> None:
        """Append a target, skipping paths that do not exist or are already listed."""
        if target is None:
            return
        if any(existing.path == target.path for existing in self.targets):
            return
        self.targets.append(target)

    @property
    def total_entries(self) -> int:
        return sum(target.entries for target in self.targets)

    def to_dict(self) -> dict[str, object]:
        return {
            "config_dir": str(self.config_dir),
            "include_artifacts": self.include_artifacts,
            "targets": [target.to_dict() for target in self.targets],
            "notes": list(self.notes),
        }


@dataclass
class ResetResult:
    """What a reset actually removed, plus anything it refused or could not remove."""

    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def configured_database_file() -> tuple[Path | None, str | None]:
    """Resolve the database file a reset may remove inside the config folder.

    Returns `(path, None)` when the database is a file hobees created inside
    `~/.hobees`, and `(None, note)` when it is not, so a reset removes the env
    entry for an external server without dropping its data.

    With no URL configured the default database path is used: that is the file
    hobees creates in `~/.hobees` on first run, and after a previous reset the env
    entry is gone, so falling back here is what keeps `hobees.db` on the slate.
    """
    home = config_dir()
    if not settings.database_url:
        return get_default_database_path(), None

    try:
        url = make_url(settings.database_url)
    except Exception as exc:
        # A malformed URL in the env file must not stop the reset; the env entry is
        # removed and no database is touched.
        return None, f"Could not read the configured database URL ({exc}), so no database was removed."
    if not url.drivername.startswith("sqlite"):
        return None, (
            f"{url.drivername.split('+')[0]} database is served outside {home}: "
            "reset removes its URL from the env file, existing rows stay on the server."
        )

    database = url.database
    if not database or database == ":memory:":
        return get_default_database_path(), (
            f"SQLite URL {settings.database_url} has no file of its own; "
            f"the default {get_default_database_path()} is removed when it exists."
        )

    path = Path(database)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_relative_to(home):
        return None, f"SQLite file {path} is outside {home} and will not be removed."
    return path, None


def _stat(path: Path) -> tuple[int, int]:
    """Return (entry_count, total_bytes) for an existing target."""
    if path.is_symlink():
        return 1, 0
    if path.is_file():
        try:
            return 1, path.stat().st_size
        except OSError:
            return 1, 0

    entries = 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                entries += 1
                total += child.stat().st_size
        except OSError:
            continue
    return entries, total


def _target(path: Path, label: str, group: TargetGroup) -> ResetTarget | None:
    """Describe an existing path as a reset target, or None when there is nothing to remove."""
    if not path.exists():
        return None
    entries, size = _stat(path)
    return ResetTarget(
        path=path,
        kind="directory" if path.is_dir() and not path.is_symlink() else "file",
        group=group,
        label=label,
        entries=entries,
        size_bytes=size,
    )


def build_plan(*, include_artifacts: bool = False) -> ResetPlan:
    """Build the reset plan for the requested scope, listing only what exists."""
    home = config_dir()
    plan = ResetPlan(include_artifacts=include_artifacts, config_dir=home)

    for relative, label in CONFIG_ITEMS:
        plan.add(_target(home / relative, label, "config"))

    database_path, database_note = configured_database_file()
    if database_note:
        plan.notes.append(database_note)
    if database_path is not None:
        for suffix in SQLITE_COMPANIONS:
            label = "local SQLite database" if not suffix else f"SQLite sidecar file {suffix}"
            plan.add(_target(Path(f"{database_path}{suffix}"), label, "config"))

    if include_artifacts:
        for relative, label in OUTPUT_ITEMS:
            plan.add(_target(home / relative, label, "output"))
        plan.add(_target(Path(settings.skills_dir), "skills library", "output"))
        plan.add(_target(Path(settings.artifacts_root), "artifacts root", "output"))

    return plan


def release_database_handle() -> None:
    """Drop the SQLAlchemy pool so a SQLite file is no longer held open.

    On Windows a file with an open handle cannot be deleted, so the database target
    has to be released before `apply_plan` removes it. This covers the reset called
    from a running process (the Web UI, or a CLI that already opened the engine).
    """
    from hobees.db.session import dispose_engine

    try:
        dispose_engine()
    except Exception:  # pragma: no cover - disposing a never-created engine is a no-op
        pass


def _remove_path(path: Path) -> None:
    """Remove one planned target, keeping symlinks as links rather than following them."""
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def allowed_roots(plan: ResetPlan) -> list[Path]:
    """Roots a reset may delete inside — defence in depth against a stray path."""
    roots = [plan.config_dir.resolve()]
    if plan.include_artifacts:
        roots.extend([Path(settings.skills_dir).resolve(), Path(settings.artifacts_root).resolve()])
    return roots


def apply_plan(plan: ResetPlan) -> ResetResult:
    """Remove every target in the plan. Callers must have confirmed with the user."""
    release_database_handle()
    roots = allowed_roots(plan)
    result = ResetResult(notes=list(plan.notes))

    for target in plan.targets:
        resolved = target.path.resolve()
        if not any(resolved == root or root in resolved.parents for root in roots):
            result.failed.append(f"{target.path}: outside the reset scope, skipped")
            continue
        try:
            _remove_path(target.path)
        except PermissionError:
            result.failed.append(f"{target.path}: {LOCKED_DATABASE_HINT}")
            continue
        except OSError as exc:
            result.failed.append(f"{target.path}: {exc}")
            continue
        result.removed.append(str(target.path))

    return result
