"""Tests for the headless `hobees reset` command and the shared core module.

Three things are checked: what a reset may remove (config scope vs the `--all`
scope), that it never touches anything outside the paths it planned, and that it
always asks the user before deleting.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from hobees.db import session as db_session

import pytest
from rich.prompt import Prompt

from hobees import config
from hobees.cli import main, reset_cmd
from hobees.cli.commands import COMMANDS, TUI_COMMANDS
from hobees.core import reset as reset_core


@pytest.fixture()
def slate(monkeypatch, tmp_path):
    """A config folder holding the files hobees creates, isolated from ~/.hobees."""
    home = tmp_path / ".hobees"
    home.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    monkeypatch.setattr(config, "_CONFIG_DIR", home)
    monkeypatch.setattr(
        config.settings, "database_url", f"sqlite:///{(home / 'hobees.db').as_posix()}"
    )
    monkeypatch.setattr(config.settings, "skills_dir", home / "skills")
    monkeypatch.setattr(config.settings, "artifacts_root", artifacts)

    (home / ".env").write_text("HOBEES_DATABASE_URL=x\n", encoding="utf-8")
    (home / ".detected").write_text("ran\n", encoding="utf-8")
    (home / "hobees.db").write_text("db\n", encoding="utf-8")
    (home / "hobees.db-wal").write_text("wal\n", encoding="utf-8")
    (home / "sessions").mkdir()
    (home / "sessions" / "work.json").write_text("{}", encoding="utf-8")
    (home / "skills").mkdir()
    (home / "skills" / "pattern.md").write_text("# skill\n", encoding="utf-8")
    (home / "scratchpad").mkdir()
    (home / "scratchpad" / "run").mkdir()
    (home / "scratchpad" / "run" / "call.txt").write_text("offloaded\n", encoding="utf-8")
    (artifacts / "dev-team").mkdir()
    (artifacts / "dev-team" / "report.md").write_text("# report\n", encoding="utf-8")

    return SimpleNamespace(home=home, artifacts=artifacts, tmp_path=tmp_path)


def planned_paths(plan) -> set[str]:
    return {str(target.path) for target in plan.targets}


def test_reset_plan_lists_only_config_scope_by_default(slate):
    plan = reset_core.build_plan()
    paths = planned_paths(plan)

    assert paths == {
        str(slate.home / ".env"),
        str(slate.home / ".detected"),
        str(slate.home / "hobees.db"),
        str(slate.home / "hobees.db-wal"),
        str(slate.home / "sessions"),
    }
    assert all(target.group == "config" for target in plan.targets)
    assert plan.notes == []
    assert plan.total_entries == 5


def test_reset_all_scope_adds_generated_output(slate):
    plan = reset_core.build_plan(include_artifacts=True)
    paths = planned_paths(plan)

    assert str(slate.home / "skills") in paths
    assert str(slate.home / "scratchpad") in paths
    assert str(slate.artifacts) in paths
    assert {target.group for target in plan.targets} == {"config", "output"}


def test_reset_on_a_clean_slate_plans_nothing(monkeypatch, tmp_path):
    home = tmp_path / "empty-hobees"
    monkeypatch.setattr(config, "_CONFIG_DIR", home)
    monkeypatch.setattr(config.settings, "database_url", None)
    monkeypatch.setattr(config.settings, "skills_dir", home / "skills")
    monkeypatch.setattr(config.settings, "artifacts_root", home / "artifacts")

    plan = reset_core.build_plan(include_artifacts=True)
    assert plan.targets == []
    assert plan.notes == []


def test_external_database_keeps_its_data_and_reports_a_note(slate, monkeypatch):
    monkeypatch.setattr(
        config.settings, "database_url", "postgresql+psycopg://u:p@localhost:5432/hobees"
    )

    plan = reset_core.build_plan()

    assert not any(target.path.name.endswith(".db") for target in plan.targets)
    assert any("postgresql database is served outside" in note for note in plan.notes)


def test_sqlite_file_outside_the_config_folder_is_not_removed(slate, monkeypatch):
    outside = slate.tmp_path / "outside.db"
    outside.write_text("db\n", encoding="utf-8")
    monkeypatch.setattr(config.settings, "database_url", f"sqlite:///{outside.as_posix()}")

    plan = reset_core.build_plan()

    assert not any(target.path == outside for target in plan.targets)
    assert any("will not be removed" in note for note in plan.notes)


def test_apply_removes_every_planned_path(slate):
    plan = reset_core.build_plan(include_artifacts=True)
    paths = planned_paths(plan)

    result = reset_core.apply_plan(plan)

    assert result.failed == []
    assert sorted(result.removed) == sorted(paths)
    for path in paths:
        assert not Path(path).exists()


def test_apply_skips_a_target_outside_the_planned_roots(slate, tmp_path):
    outside = tmp_path / "user_config.json"
    outside.write_text("{}", encoding="utf-8")
    plan = reset_core.build_plan()
    plan.targets.append(reset_core.ResetTarget(path=outside, kind="file", group="config", label="stray"))

    result = reset_core.apply_plan(plan)

    assert any("outside the reset scope" in failure for failure in result.failed)
    assert outside.exists()


def test_apply_reports_a_path_that_disappeared_after_the_plan(slate):
    env_path = slate.home / ".env"
    plan = reset_core.build_plan()
    env_path.unlink()

    result = reset_core.apply_plan(plan)

    assert len(result.failed) == 1
    assert str(env_path) in result.failed[0]
    assert not any("outside the reset scope" in failure for failure in result.failed)
    assert str(slate.home / "sessions") in result.removed


def test_cli_reset_always_confirms_and_cancels_without_yes(slate, monkeypatch, capsys):
    monkeypatch.setattr(reset_cmd, "_confirm_yes", lambda question: False)

    reset_cmd.reset_command()

    out = capsys.readouterr().out
    assert "Reset the hobees slate (config only)" in out
    assert "cancelled" in out
    assert (slate.home / ".env").exists()


def test_cli_reset_proceeds_when_the_user_answers_yes(slate, monkeypatch, capsys):
    monkeypatch.setattr(reset_cmd, "_confirm_yes", lambda question: True)

    reset_cmd.reset_command()

    out = capsys.readouterr().out
    assert "Removed" in out
    assert not (slate.home / ".env").exists()
    assert not (slate.home / "hobees.db").exists()
    assert (slate.home / "skills").exists()


def test_cli_reset_all_removes_generated_output_too(slate, monkeypatch, capsys):
    monkeypatch.setattr(reset_cmd, "_confirm_yes", lambda question: True)

    reset_cmd.reset_command(include_artifacts=True)

    out = capsys.readouterr().out
    assert "config + generated output" in out
    assert not (slate.home / "skills").exists()
    assert not (slate.home / "scratchpad").exists()
    assert not slate.artifacts.exists()


def test_cli_reset_reports_a_clean_slate_without_asking(slate, monkeypatch, capsys):
    monkeypatch.setattr(config, "_CONFIG_DIR", slate.tmp_path / "empty-hobees")
    monkeypatch.setattr(config.settings, "skills_dir", slate.tmp_path / "empty-hobees" / "skills")
    monkeypatch.setattr(config.settings, "artifacts_root", slate.tmp_path / "empty-hobees" / "artifacts")
    confirm = Mock()
    monkeypatch.setattr(reset_cmd, "_confirm_yes", confirm)

    reset_cmd.reset_command()

    confirm.assert_not_called()
    assert "already clean" in capsys.readouterr().out


def test_confirmation_accepts_only_y_or_yes(monkeypatch):
    for answer, expected in (("Y", True), ("yes", True), ("YeS", True), ("n", False), ("maybe", False)):
        monkeypatch.setattr(Prompt, "ask", lambda question, default="n", _answer=answer: _answer)
        assert reset_cmd._confirm_yes("Proceed?") is expected

    def closed(question, default="n"):
        raise EOFError

    monkeypatch.setattr(Prompt, "ask", closed)
    assert reset_cmd._confirm_yes("Proceed?") is False


def test_reset_is_headless_only_and_not_a_slash_command():
    assert "reset" not in COMMANDS
    assert "reset" not in TUI_COMMANDS
    assert "reset" in {command.name for command in main.app.registered_commands}


def test_reset_startup_does_not_recreate_the_file_it_removes(monkeypatch, tmp_path, capsys):
    home = tmp_path / ".hobees"
    monkeypatch.setattr(config, "_CONFIG_DIR", home)
    monkeypatch.setattr(config.settings, "database_url", None)
    monkeypatch.setattr(config.settings, "config_path", tmp_path / "hobees.yaml")
    sync = Mock()
    monkeypatch.setattr(main, "_sync_startup_config", sync)

    main._root(SimpleNamespace(resilient_parsing=False, invoked_subcommand="reset"))

    sync.assert_not_called()
    assert not (home / ".env").exists()
    assert "hobees.db" not in capsys.readouterr().out


def test_allowed_roots_cover_only_the_planned_scopes(slate):
    assert reset_core.allowed_roots(reset_core.build_plan()) == [slate.home.resolve()]

    roots = reset_core.allowed_roots(reset_core.build_plan(include_artifacts=True))
    assert set(roots) == {
        slate.home.resolve(),
        (slate.home / "skills").resolve(),
        slate.artifacts.resolve(),
    }


def test_malformed_database_url_leaves_the_database_untouched(slate, monkeypatch):
    monkeypatch.setattr(config.settings, "database_url", "sqlite://D:/x/y.db")

    plan = reset_core.build_plan()

    assert not any(target.path.name.endswith(".db") for target in plan.targets)
    assert any("Could not read the configured database URL" in note for note in plan.notes)

def test_reset_plans_the_default_database_when_no_url_is_configured(slate, monkeypatch):
    """The slate default lives in ~/.hobees, so it stays on the plan without an env URL."""
    monkeypatch.setattr(config.settings, "database_url", None)

    plan = reset_core.build_plan()

    assert str(slate.home / "hobees.db") in planned_paths(plan)
    assert planned_paths(plan) == {
        str(slate.home / ".env"),
        str(slate.home / ".detected"),
        str(slate.home / "sessions"),
        str(slate.home / "hobees.db"),
        str(slate.home / "hobees.db-wal"),
    }


def test_in_memory_url_still_falls_back_to_the_default_file(slate, monkeypatch):
    monkeypatch.setattr(config.settings, "database_url", "sqlite:///:memory:")

    plan = reset_core.build_plan()

    assert str(slate.home / "hobees.db") in planned_paths(plan)
    assert any("no file of its own" in note for note in plan.notes)


def test_apply_releases_the_database_handle_before_deleting(slate, monkeypatch):
    """On Windows a file with an open handle cannot be deleted, so the pool goes first."""
    order = []
    monkeypatch.setattr(db_session, "dispose_engine", lambda: order.append("dispose"))
    monkeypatch.setattr(
        reset_core,
        "_remove_path",
        lambda path: order.append(f"remove:{Path(path).name}"),
    )

    plan = reset_core.build_plan()
    result = reset_core.apply_plan(plan)

    assert order[0] == "dispose"
    assert "remove:hobees.db" in order
    assert result.failed == []


def test_apply_reports_a_locked_database_with_a_useful_hint(slate, monkeypatch):
    db_path = slate.home / "hobees.db"
    plan = reset_core.build_plan()

    def blocked(path):
        if Path(path) == db_path:
            raise PermissionError("[WinError 32] The process cannot access the file")
        Path(path).unlink()

    monkeypatch.setattr(reset_core, "_remove_path", blocked)

    result = reset_core.apply_plan(plan)

    assert str(db_path) not in [Path(item).name for item in result.removed]
    assert any("held open by another process" in failure for failure in result.failed)
    assert db_path.exists()
