"""Tests for the headless goal input: argument, `--goal-file`, or a pipe."""

from __future__ import annotations

import inspect
import io
import sys

import pytest
import typer

from hobees.cli import goal_input, hive_cmd, main


def test_goal_argument_wins_over_file_and_stdin(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped"))
    goal_file = tmp_path / "goal.txt"
    goal_file.write_text("from the file", encoding="utf-8")

    assert goal_input.resolve_goal("from argument", str(goal_file)) == "from argument"


def test_goal_file_is_read_when_no_argument_is_given(tmp_path, monkeypatch):
    goal_file = tmp_path / "goal.txt"
    goal_file.write_text("  from the file\nsecond line\n", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped"))

    assert goal_input.resolve_goal(None, str(goal_file)) == "from the file\nsecond line"


def test_dash_reads_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("from stdin\n"))
    assert goal_input.resolve_goal("-", None) == "from stdin"


def test_piped_stdin_is_used_when_nothing_else_is_given(monkeypatch):
    piped = io.StringIO("piped goal\n")
    monkeypatch.setattr(sys, "stdin", piped)
    assert goal_input.resolve_goal(None, None) == "piped goal"

    terminal = io.StringIO("")
    monkeypatch.setattr(terminal, "isatty", lambda: True)
    monkeypatch.setattr(sys, "stdin", terminal)
    assert goal_input.resolve_goal(None, None) is None


def test_missing_goal_file_and_empty_goal_exit_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(typer.Exit):
        goal_input.resolve_goal(None, str(tmp_path / "absent.txt"))
    with pytest.raises(typer.Exit):
        goal_input.require_goal(None)
    assert goal_input.require_goal("  keep the text  ") == "keep the text"


def test_goal_file_option_is_registered_on_every_headless_command():
    assert "goal_file" in inspect.signature(main.prompt).parameters
    assert "goal_file" in inspect.signature(main.run_cmd).parameters
    assert "goal_file" in inspect.signature(hive_cmd.cli_run).parameters
