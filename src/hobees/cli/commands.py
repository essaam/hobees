"""Slash-command catalog for the hobees front-ends.

The legacy shell and the TUI both drive everything through ``/`` commands. This
module is the single source of truth for which commands exist, so the
completion menu, ``/help`` output and command dispatch cannot drift apart.

Deliberately dependency-free: it is imported at CLI startup, before any
front-end-specific prompt_toolkit components are needed.
"""

from __future__ import annotations

__all__ = ["CommandSpec", "COMMANDS", "TUI_COMMANDS"]

# command name -> (description, sub-commands)
CommandSpec = tuple[str, tuple[str, ...]]

#: Every command understood by the legacy interactive shell.
COMMANDS: dict[str, CommandSpec] = {
    "provider": (
        "Manage LLM providers; 'models' lists a provider's models, 'use' switches to one, 'edit' edits details",
        ("add", "list", "test", "remove", "edit", "models", "use"),
    ),
    "detect_providers": ("Scan for available cloud and local providers, then register them", ()),
    "assistant": (
        "Configure the default assistant agent (persisted across launches)",
        ("show", "use", "model"),
    ),
    "bee": ("Manage Worker Bees", ("create", "list", "update", "delete", "thinking")),
    "hive": ("Manage Working Hives", ("create", "add-bee", "remove-bee", "list", "remove", "use", "auto", "thinking", "artifacts", "trace")),
    "chat": ("Chat directly with a Bee or Hive", ("bee", "hive", "list")),
    "goal": ("Run a goal through the Queen (auto-mode)", ()),
    "usage": ("Query usage telemetry", ("all", "bee", "hive", "provider", "day")),
    "thinking": ("Set session-wide thinking level override", ("off", "low", "medium", "high", "auto")),
    "compact": ("Compress the active thread's message history", ()),
    "memory": ("Cross-session scoped memory store", ("list", "add", "forget", "show")),
    "skill": ("Progressive skill library", ("list", "show", "create", "save-last", "assign", "unassign", "sync")),
    "session": ("Named session management", ("save", "load", "list", "delete")),
    "quit": ("Exit the shell", ()),
    "exit": ("Exit the shell", ()),
    "help": ("Show this help", ()),
    "cancel": ("Cancel the current running task", ()),
}

#: Commands the TUI implements (a subset -- keep in sync with
#: ``HobeesTUI._handle_command``). Advertising more here would hand the user
#: completions that answer "Unknown command".
TUI_COMMANDS: dict[str, CommandSpec] = {
    "provider": (
        "Manage LLM providers; 'models' lists a provider's models, 'use' switches to one, 'edit' edits details",
        ("add", "list", "models", "use", "edit"),
    ),
    "assistant": (
        "Configure the default assistant agent (persisted across launches)",
        ("show", "use", "model"),
    ),
    "hive": COMMANDS["hive"],
    "chat": COMMANDS["chat"],
    "thinking": COMMANDS["thinking"],
    "clear": ("Clear the output pane", ()),
    "help": ("Show this help", ()),
    "quit": COMMANDS["quit"],
    "exit": COMMANDS["exit"],
    "cancel": COMMANDS["cancel"],
}