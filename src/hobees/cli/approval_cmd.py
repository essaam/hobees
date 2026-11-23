"""Approval-level handlers — shared by the headless Typer command (``hobees approvals``)
and the interactive slash commands (``/approvals`` / ``/permissions``).

Two scopes, matching the HITL spec (specs/HITL.md §2.3):

* **session** — an override that lives only for the current front-end process.
* **global** — persisted to the user's hobees env file, so every later session
  starts from it.

Resolution order: CLI flag → session override → global setting (env file) →
context default (`interactive` on a TTY, `strict` otherwise).

The accepted words come from :mod:`hobees.cli.commands`, which is also what the
completion menus read — so a suggestion is never a word this handler rejects.
Heavy imports stay inside the functions to keep CLI startup fast.
"""

from __future__ import annotations

import os
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from hobees.cli.commands import (
    APPROVAL_LEVELS,
    APPROVAL_LEVEL_MEANINGS,
    APPROVAL_WORDS,
    CLEAR_WORD,
    DEFAULT_WORD,
    GLOBAL_WORD,
    SET_WORD,
    SHOW_WORD,
)
from hobees.cli.icons import APP, ERROR, SUCCESS

console = Console()

__all__ = [
    "APPROVAL_HELP",
    "ARG_HELP",
    "CLI_USAGE",
    "ICON_OF",
    "SLASH_USAGE",
    "STYLE_OF",
    "accepted_words",
    "apply_level",
    "approvals_command",
    "effective_level",
    "handle",
    "levels_help",
    "normalize_level",
    "parse_scope",
    "permissions",
    "source_of",
    "status_text",
]

SHOW_WORDS = (SHOW_WORD,)
CLEAR_WORDS = (DEFAULT_WORD, CLEAR_WORD)

SLASH_USAGE = (
    "Usage: /approvals [show|set] <level|default> "
    "| /approvals global <level|default>"
)
CLI_USAGE = (
    "Usage: hobees approvals [show|set] <level>      persists globally\n"
    "       hobees approvals --session <level>       this run only, nothing saved\n"
    "       hobees approvals clear                   remove the persisted setting"
)

#: Style/icon keys for the ``(kind, message, level)`` triple `handle()` returns.
STYLE_OF = {"status": "info", "ok": "success", "error": "error"}
ICON_OF = {"status": APP, "ok": SUCCESS, "error": ERROR}


def levels_help(header: str = "Levels:") -> str:
    """The level legend shared by `--help`, `/approvals` usage and the shell help."""
    width = max(len(level) for level in APPROVAL_LEVELS)
    lines = [header]
    for level in APPROVAL_LEVELS:
        lines.append(f"  {level:<{width}}  {APPROVAL_LEVEL_MEANINGS[level]}")
    return "\n".join(lines)


def accepted_words() -> tuple[str, ...]:
    """Exactly the words `handle()` understands — same tuple the menus suggest."""
    return APPROVAL_WORDS


def normalize_level(raw: str) -> str | None:
    """Return ``raw`` normalised to a valid level, or ``None`` when it is not one."""
    value = raw.strip().lower()
    return value if value in APPROVAL_LEVELS else None


def parse_scope(args: list[str]) -> tuple[str, list[str]]:
    """Split ``[global] <level>``; the default scope is the current session."""
    if args and args[0].lower() == "global":
        return "global", args[1:]
    return "session", args


def source_of(session_level: str | None = None) -> str:
    """Where the effective level comes from for the current process."""
    if session_level:
        return "session override"
    from hobees.config import settings

    if os.getenv("HOBEES_APPROVAL_MODE") or settings.approval_mode:
        return "global"
    return "context default"


def effective_level(
    session_level: str | None = None,
    interactive: bool | None = None,
) -> tuple[str, str]:
    """Return ``(resolved level, source)`` for the given session override."""
    from hobees.core.approval import resolve_approval_mode

    resolved = resolve_approval_mode(session_mode=session_level, interactive=interactive)
    trusted_session = session_level if normalize_level(session_level or "") else None
    return resolved, source_of(trusted_session)


def apply_level(
    raw: str,
    *,
    scope: str = "session",
    session_level: str | None = None,
) -> tuple[bool, str, str | None]:
    """Apply one level word for ``scope``.

    Returns ``(ok, message, new_session_level)``. A global change persists to
    ``~/.hobees/.env`` and drops the session override so the new default applies;
    a session change only affects this process. ``default``/``clear`` removes the
    setting for whichever scope it is applied to.
    """
    from hobees.core.approval import APPROVAL_MODES
    from hobees.config import settings

    word = raw.strip().lower()

    if word in CLEAR_WORDS:
        if scope == "global":
            from hobees.config import set_global_approval_mode

            set_global_approval_mode(None)
            return True, "Global approval level cleared; using the context default.", None
        fallback = settings.approval_mode or "context default"
        return True, f"Session approval override cleared; using {fallback}.", None

    level = normalize_level(word)
    if level is None:
        return (
            False,
            f"Invalid approval level: {raw}. Choose {', '.join(APPROVAL_LEVELS)} or default.",
            session_level,
        )

    if scope == "global":
        from hobees.config import set_global_approval_mode

        set_global_approval_mode(level)
        return True, f"Global approval level set to '{level}'.", None

    return True, f"Session approval level set to '{level}'.", level


def status_text(
    session_level: str | None = None,
    *,
    interactive: bool | None = None,
    usage: str = SLASH_USAGE,
) -> str:
    """The current level + usage + level legend report."""
    level, source = effective_level(session_level, interactive=interactive)
    return (
        f"Approval level ({source}): {level}\n{usage}\n"
        + levels_help("Levels (what happens to a require_approval tool):")
    )


def handle(
    args: list[str],
    session_level: str | None,
    *,
    interactive: bool | None = None,
    usage: str = SLASH_USAGE,
    default_scope: str = "session",
) -> tuple[str, str, str | None]:
    """Resolve one request from either front-end.

    Returns ``(kind, message, new_session_level)`` where ``kind`` is ``status``
    (nothing to change), ``ok`` (applied) or ``error``. Accepted shape:
    ``[global] [set] <show|level|default>``; an empty request means "show".
    ``default_scope`` is the scope used when none is given — the front-ends use
    ``session``, the headless command uses ``global``.
    """
    values = [value for value in args if value.strip()]
    scope = default_scope
    if values and values[0].lower() == GLOBAL_WORD:
        scope, values = "global", values[1:]
    if values and values[0].lower() == SET_WORD:
        values = values[1:]

    if not values:
        return "status", status_text(session_level, interactive=interactive, usage=usage), session_level
    if len(values) > 1:
        return (
            "error",
            f"Specify one level: {', '.join(APPROVAL_LEVELS)}, default, or show.",
            session_level,
        )
    if values[0].lower() in SHOW_WORDS:
        return "status", status_text(session_level, interactive=interactive, usage=usage), session_level

    ok, message, new_level = apply_level(values[0], scope=scope, session_level=session_level)
    return ("ok" if ok else "error"), message, new_level


APPROVAL_HELP = """
Show or set the tool approval level.

Usage:
  hobees approvals                      effective level and where it comes from
  hobees approvals show                 same as above
  hobees approvals set <level>          persist globally (~/.hobees/.env)
  hobees approvals <level>              same, short form
  hobees approvals clear                remove the persisted global setting
  hobees approvals --session <level>    level for this run only, nothing saved
  hobees approvals --json               machine-readable output

Levels (what happens to a tool a Bee declared in require_approval):
  interactive   prompt live: Approve / Edit / Reject  (default on a TTY)
  auto          run without prompting                 (trusted container, CI, cron)
  strict        never run; return a policy rejection
  pause         checkpoint the interrupt, print JSON, exit 0 for a later
                `hobees hive run --resume-decision approve`

Precedence: --approval-mode flag > session override > HOBEES_APPROVAL_MODE >
context default. Inside the interactive shell or TUI use /approvals <level>
(alias /permissions), or /approvals global <level> to persist it.
"""


ARG_HELP = "show | set <level> | clear | <level>; levels: " + ", ".join(APPROVAL_LEVELS)

APPROVAL_HELP = (
    "Show or set the tool approval level.\n\n"
    "Usage:\n"
    "  hobees approvals                   show the level and where it comes from\n"
    "  hobees approvals show              same as above\n"
    "  hobees approvals set <level>       persist globally (~/.hobees/.env)\n"
    "  hobees approvals <level>           same, short form\n"
    "  hobees approvals clear             remove the persisted global setting\n"
    "  hobees approvals --session <level> this run only, nothing saved\n"
    "  hobees approvals --json            machine-readable output\n\n"
    + levels_help("Levels (what happens to a tool in require_approval):")
    + "\n\nPrecedence: --approval-mode flag > session override >\n"
    "HOBEES_APPROVAL_MODE > context default (interactive on a TTY, strict\n"
    "headless). In the shell or TUI use /approvals <level> (alias\n"
    "/permissions), or /approvals global <level> to persist it.\n"
)


def approvals_command(
    args: Annotated[list[str], typer.Argument(help=ARG_HELP)] = [],
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            help="Resolve a level for this run only, without persisting it.",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the effective level as JSON."),
    ] = False,
) -> None:
    """Placeholder replaced by APPROVAL_HELP below."""
    from hobees.config import settings

    session_level = None
    if session:
        session_level = normalize_level(session)
        if session_level is None:
            console.print(
                f"{ERROR} Invalid approval level: {session}. "
                f"Choose {', '.join(APPROVAL_LEVELS)}."
            )
            raise typer.Exit(code=1)

    kind, message, new_level = handle(
        args,
        session_level,
        interactive=sys.stdin.isatty(),
        usage=CLI_USAGE,
        default_scope="global",
    )
    if kind == "error":
        console.print(f"{ERROR} {message}")
        raise typer.Exit(code=1)

    if as_json:
        import json

        level, source = effective_level(new_level, interactive=sys.stdin.isatty())
        console.print(
            json.dumps(
                {
                    "level": level,
                    "source": source,
                    "global": settings.approval_mode,
                    "session": new_level,
                },
                sort_keys=True,
            )
        )
        return

    console.print(f"{ICON_OF[kind]} {escape(message)}")


# Typer builds `--help` from the docstring: the first line becomes the one-line
# summary in `hobees --help`, the rest is the full explanation.
approvals_command.__doc__ = APPROVAL_HELP

# ``hobees permissions`` is the headless alias of ``hobees approvals``; the
# interactive front-ends accept both spellings too.
permissions = approvals_command

