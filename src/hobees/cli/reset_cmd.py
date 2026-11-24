"""`hobees reset` — clean the hobees slate.

Headless Typer command only: the interactive shell and the TUI deliberately do
not offer it, because a reset is a one-shot destructive operation that must be
confirmed. The web app exposes the same scope on the Studio page.

`hobees reset` removes the env file, databases and config files hobees created
inside `~/.hobees`. `hobees reset --all` additionally removes generated output:
the skills library, the scratchpad cache and the artifacts root. Environment
variables in the user's shell are never changed.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from hobees.cli.icons import APP, ERROR, SUCCESS, WARN
from hobees.core import reset as reset_core

console = Console()

_CONFIRM_QUESTION = "Proceed with reset? Type Y (yes) to remove these files"


def _confirm_yes(question: str) -> bool:
    """Ask for an explicit Y(es); any other answer, or no answer at all, means 'no'."""
    try:
        answer = Prompt.ask(question, default="n")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _format_size(total_bytes: int) -> str:
    if total_bytes >= 1024 * 1024:
        return f"{total_bytes / (1024 * 1024):.1f} MB"
    if total_bytes >= 1024:
        return f"{total_bytes / 1024:.1f} KB"
    return f"{total_bytes} B"


def _contents_cell(target: reset_core.ResetTarget) -> str:
    if target.kind == "directory":
        return f"{target.entries} file(s), {_format_size(target.size_bytes)}"
    return _format_size(target.size_bytes)


SCOPE_TITLES = {"config": "Config scope", "output": "Generated output"}


def print_plan(plan: reset_core.ResetPlan) -> None:
    """List what exists, grouped by scope, so the confirmation shows whole paths."""
    for group in ("config", "output"):
        targets = [target for target in plan.targets if target.group == group]
        if not targets:
            continue
        console.print(f"  [bold]{SCOPE_TITLES[group]}[/bold]")
        for target in targets:
            console.print(
                f"    {escape(target.label)}: [dim]{escape(str(target.path))}[/dim] "
                f"[dim]({_contents_cell(target)})[/dim]"
            )

    for note in plan.notes:
        console.print(f"  {WARN} {escape(note)}")
    console.print(
        f"  [dim]{plan.total_entries} file(s) across {len(plan.targets)} target(s); "
        "shell environment variables are not changed.[/dim]"
    )


def reset_command(
    include_artifacts: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Also remove generated output: artifacts, skills and the scratchpad cache",
        ),
    ] = False,
) -> None:
    """Clean the hobees slate: env file, databases and config files inside ~/.hobees.

    Confirmation is always required — answer Y (yes) to proceed, anything else
    cancels and nothing is removed. Only files hobees created inside `~/.hobees`
    are touched, the skills/artifacts roots for `--all`, plus the SQLite
    sidecar files. Variables exported in the shell are left alone, and a database
    configured outside `~/.hobees` is never dropped.

    Examples::

        hobees reset
        hobees reset --all
    """
    plan = reset_core.build_plan(include_artifacts=include_artifacts)

    if not plan.targets:
        console.print(f"{WARN} Nothing to remove — the hobees slate is already clean.")
        return

    scope = "config + generated output" if include_artifacts else "config only"
    console.print(f"\n{APP} [bold]Reset the hobees slate[/bold] ({scope})\n")
    print_plan(plan)

    if not _confirm_yes(_CONFIRM_QUESTION):
        console.print(f"{WARN} Reset cancelled. Nothing was removed.")
        return

    result = reset_core.apply_plan(plan)
    console.print()
    for path in result.removed:
        console.print(f"{SUCCESS} Removed {escape(path)}")
    for failure in result.failed:
        console.print(f"{ERROR} {escape(failure)}")

    if not result.removed:
        console.print(f"{WARN} Nothing was removed.")
        return

    if result.failed:
        console.print(
            f"\n  {WARN} Some paths were left behind. Close any running hobees process "
            "(web app, shell, another terminal) and run reset again."
        )
        raise typer.Exit(code=1)

    console.print(
        "\n  The slate is clean. Detection, the default env file and the database "
        "are rebuilt on the next launch; run [bold]hobees init[/bold] to ensure the "
        "schema immediately."
    )
