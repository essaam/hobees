"""prompt_toolkit completion for slash commands and ``@``-prefixed paths.

Typing ``/`` offers available commands; typing ``@`` offers paths from the
current folder. The command catalog lives in :mod:`hobees.cli.commands`. This
module is only imported when a front-end builds a prompt, keeping
prompt_toolkit out of the CLI cold-start path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Iterator, Mapping

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings

from hobees.cli.commands import CommandSpec

logger = logging.getLogger(__name__)

__all__ = [
    "FilePathCompleter",
    "FilePathCompletion",
    "SlashCommandCompleter",
    "add_completion_accept_binding",
    "accept_completion_or_submit",
]


class FilePathCompletion(Completion):
    """A path suggestion, distinct from slash-command suggestions."""


class FilePathCompleter(Completer):
    """Complete paths after ``@`` using entries relative to the current folder."""

    def __init__(self, enabled: Callable[[], bool] | None = None) -> None:
        self._enabled = enabled

    def get_completions(
        self, document: Document, complete_event: object
    ) -> Iterator[Completion]:
        if self._enabled is not None and not self._enabled():
            return

        text = document.text_before_cursor
        at_position = text.rfind("@")
        if at_position < 0:
            return
        if at_position and not text[at_position - 1].isspace():
            return

        typed_path = text[at_position + 1 :]
        if typed_path.endswith("/"):
            directory_text = typed_path
            prefix = ""
        else:
            typed = Path(typed_path)
            directory_text = "" if str(typed.parent) == "." else str(typed.parent)
            prefix = typed.name

        if any(character.isspace() for character in prefix):
            return

        try:
            directory = (Path.cwd() / directory_text).resolve()
            entries = list(directory.iterdir())
        except OSError as exc:
            logger.warning(
                "Cannot list paths for completion in %s: %s",
                directory_text or ".",
                exc,
            )
            return

        matching_entries: list[tuple[Path, bool]] = []
        for entry in entries:
            if entry.name.startswith(".") and not prefix.startswith("."):
                continue
            if not entry.name.casefold().startswith(prefix.casefold()):
                continue
            matching_entries.append((entry, entry.is_dir()))

        matching_entries.sort(key=lambda item: (not item[1], item[0].name.casefold()))
        for entry, is_directory in matching_entries:
            kind = "folder" if is_directory else "file"
            yield FilePathCompletion(
                entry.name,
                start_position=-len(prefix),
                display=f"{entry.name}{'/' if is_directory else ''}",
                display_meta=kind,
            )

        yield FilePathCompletion(
            "../",
            start_position=-len(prefix),
            display="..",
            display_meta="parent directory",
        )


def add_completion_accept_binding(key_bindings: KeyBindings) -> None:
    """Use Enter to accept a selected path completion, otherwise submit input."""

    @key_bindings.add("enter", eager=True)
    def _(event) -> None:
        accept_completion_or_submit(event.current_buffer)


def accept_completion_or_submit(buffer: Buffer) -> None:
    """Apply a path suggestion, or accept the input when none is selected."""
    completion_state = buffer.complete_state

    if completion_state is not None:
        completion = completion_state.current_completion
        if completion is None:
            completion = next(
                (
                    item
                    for item in completion_state.completions
                    if isinstance(item, FilePathCompletion)
                ),
                None,
            )
        if isinstance(completion, FilePathCompletion):
            buffer.apply_completion(completion)
            return

    buffer.validate_and_handle()


class SlashCommandCompleter(Completer):
    """Complete ``/command`` and ``/command <sub>`` while the user types.

    Nothing is offered unless the line starts with ``/``, so normal chat input
    is never interfered with.
    """

    def __init__(
        self,
        commands: Mapping[str, CommandSpec],
        enabled: Callable[[], bool] | None = None,
    ) -> None:
        self._commands = commands
        self._enabled = enabled

    def get_completions(
        self, document: Document, complete_event: object
    ) -> Iterator[Completion]:
        if self._enabled is not None and not self._enabled():
            return

        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        body = text[1:]
        if " " in body:
            name, _, rest = body.partition(" ")
            spec = self._commands.get(name.lower())
            if spec is None:
                return
            for sub in spec[1]:
                if sub.startswith(rest):
                    yield Completion(sub, start_position=-len(rest), display=sub)
            return

        for name, (description, _subs) in sorted(self._commands.items()):
            if name.startswith(body):
                yield Completion(
                    f"/{name}",
                    start_position=-(len(body) + 1),
                    display=f"/{name}",
                    display_meta=description,
                )
