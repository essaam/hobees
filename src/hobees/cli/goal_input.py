"""Where a headless run takes its goal from.

A goal can be several paragraphs long, which is why a file or piped stdin is a
better carrier in containers and CI than a shell-quoted argument or an environment
variable: no quoting, no size limit, and nothing that leaks into `docker inspect`
or CI logs. `resolve_goal()` keeps one precedence for every front-end:

    explicit argument (or `-` for stdin)  >  --goal-file <path>  >  piped stdin

The value is never trusted as a policy — it is just text handed to the graph.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from hobees.cli.icons import ERROR

console = Console()


def read_goal_text(source: str) -> str:
    """Read goal text from a path, or from stdin when the source is `-`."""
    if source == "-":
        return sys.stdin.read()
    path = Path(source).expanduser()
    if not path.is_file():
        console.print(f"{ERROR} Goal file not found: {escape(str(path))}")
        raise typer.Exit(code=1)
    return path.read_text(encoding="utf-8")


def resolve_goal(goal: str | None, goal_file: str | None) -> str | None:
    """Return the goal to run, or None when the caller gave nothing usable."""
    if goal == "-":
        return sys.stdin.read().strip() or None
    if goal:
        return goal.strip()
    if goal_file:
        return read_goal_text(goal_file).strip() or None
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return piped
    return None


def require_goal(goal: str | None) -> str:
    """Exit with the usable ways to supply a goal, so a silent empty run never happens."""
    if not goal:
        console.print(
            f"{ERROR} No goal to run. Pass it as an argument, with --goal-file <path>, "
            "or pipe it on stdin (e.g. `hobees run - < goal.txt`)."
        )
        raise typer.Exit(code=1)
    return goal.strip()


__all__ = ["read_goal_text", "resolve_goal", "require_goal"]
