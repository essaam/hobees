"""Tests for the approval-level surface: the headless CLI command, the interactive
slash commands (`/approvals` and its `/permissions` alias), and the shared
session/global resolution every front-end uses."""

import asyncio
import json
import re
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
import typer
from typer.testing import CliRunner

from hobees import config
from hobees.cli import main, shell
from hobees.cli.approval_cmd import (
    accepted_words,
    apply_level,
    effective_level,
    handle,
    normalize_level,
    parse_scope,
)
from hobees.cli.commands import (
    APPROVAL_LEVELS,
    APPROVAL_LEVEL_MEANINGS,
    CLEAR_WORD,
    DEFAULT_WORD,
    COMMANDS,
    TUI_COMMANDS,
)
from hobees.cli.tui import HobeesTUI
from hobees.core.approval import APPROVAL_MODES, resolve_approval_mode


def _isolate(monkeypatch, global_mode=None):
    """Pin the resolver to a known baseline (no env file, no saved setting)."""
    monkeypatch.delenv("HOBEES_APPROVAL_MODE", raising=False)
    monkeypatch.setattr(config.settings, "approval_mode", global_mode)


@pytest.fixture(autouse=True)
def isolated_approval_settings(monkeypatch, tmp_path):
    """Every test starts clean and ends clean — no real ~/.hobees/.env writes."""
    monkeypatch.delenv("HOBEES_APPROVAL_MODE", raising=False)
    monkeypatch.setattr(config.settings, "approval_mode", None)
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config.settings, "config_path", None)
    monkeypatch.setattr(config.settings, "database_url", "sqlite:///:memory:")
    yield


def runner():
    return CliRunner()


def plain(output: str) -> str:
    """Help text as authored, without Rich styling codes or panel wrapping noise.

    Typer renders help with a Rich console, which emits ANSI codes in CI and
    wraps lines at the terminal width; both can split a phrase that the help
    actually contains. Strip the codes and collapse whitespace so the assertions
    check the text itself rather than its rendering.
    """
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", output).split())


def test_normalise_and_scope_parsing():
    assert normalize_level("  AUTO  ") == "auto"
    assert normalize_level("yes-please") is None
    assert set(APPROVAL_MODES) == {"interactive", "auto", "strict", "pause"}
    assert parse_scope(["auto"]) == ("session", ["auto"])
    assert parse_scope(["global", "strict"]) == ("global", ["strict"])


def test_precedence_flag_then_session_then_global(monkeypatch):
    _isolate(monkeypatch, global_mode="strict")

    # CLI flag wins over the session override.
    assert resolve_approval_mode("pause", session_mode="auto") == "pause"
    # Session override wins over the saved global setting.
    assert resolve_approval_mode(session_mode="auto") == "auto"
    assert resolve_approval_mode() == "strict"

    monkeypatch.setenv("HOBEES_APPROVAL_MODE", "interactive")
    assert resolve_approval_mode(session_mode="auto") == "auto"
    # An unusable value can never widen a policy.
    assert resolve_approval_mode(session_mode="yes-please") == "interactive"


def test_context_default_when_nothing_is_set(monkeypatch):
    _isolate(monkeypatch)
    assert effective_level(None, interactive=True) == ("interactive", "context default")
    assert effective_level(None, interactive=False) == ("strict", "context default")
    assert effective_level("auto", interactive=False) == ("auto", "session override")
    _isolate(monkeypatch, global_mode="strict")
    assert effective_level(None, interactive=False) == ("strict", "global")


def test_set_global_approval_mode_persists_to_env_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    _isolate(monkeypatch)

    config.set_global_approval_mode("auto")
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert env.strip() == "HOBEES_APPROVAL_MODE=auto"
    assert config.settings.approval_mode == "auto"

    # Re-setting replaces the line instead of appending duplicates.
    config.set_global_approval_mode("strict")
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert env.count("HOBEES_APPROVAL_MODE") == 1
    assert env.strip() == "HOBEES_APPROVAL_MODE=strict"

    config.set_global_approval_mode(None)
    assert "HOBEES_APPROVAL_MODE" not in (tmp_path / ".env").read_text(encoding="utf-8")
    assert config.settings.approval_mode is None


def test_apply_level_scope_semantics(monkeypatch):
    _isolate(monkeypatch)
    persisted = []
    monkeypatch.setattr(config, "set_global_approval_mode", lambda mode: persisted.append(mode))

    ok, message, new_level = apply_level("auto", scope="session", session_level="pause")
    assert ok and new_level == "auto" and "Session" in message
    # A session change must not touch the persisted global setting.
    assert persisted == []

    ok, message, new_level = apply_level("strict", scope="global")
    assert ok and persisted == ["strict"] and new_level is None
    assert message == "Global approval level set to 'strict'."

    ok, _, new_level = apply_level("default", scope="session", session_level="auto")
    assert ok and new_level is None

    ok, message, new_level = apply_level("nope", scope="session", session_level="auto")
    assert not ok and new_level == "auto" and "Invalid approval level" in message


def _cli(monkeypatch, tmp_path, args, global_mode=None):
    """Run `hobees approvals ...` without touching the user's real config dir."""
    _isolate(monkeypatch, global_mode)
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config.settings, "config_path", None)
    monkeypatch.setattr(config.settings, "database_url", "sqlite:///:memory:")
    return runner().invoke(main.app, args, catch_exceptions=False)


def test_headless_cli_reports_and_persists_levels(monkeypatch, tmp_path):
    result = _cli(monkeypatch, tmp_path, ["approvals"], global_mode="strict")
    assert result.exit_code == 0
    assert "Approval level (global): strict" in plain(result.output)

    result = _cli(monkeypatch, tmp_path, ["approvals", "set", "auto"])
    assert result.exit_code == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8").strip() == "HOBEES_APPROVAL_MODE=auto"

    # The bare form (`hobees approvals auto`) is the same command.
    result = _cli(monkeypatch, tmp_path, ["approvals", "pause"])
    assert "Global approval level set to 'pause'." in plain(result.output)

    result = _cli(monkeypatch, tmp_path, ["approvals", "clear"])
    assert "Global approval level cleared" in plain(result.output)

    bad = _cli(monkeypatch, tmp_path, ["approvals", "yes-please"])
    assert bad.exit_code == 1
    assert "Invalid approval level" in plain(bad.output)


def test_headless_cli_session_flag_does_not_persist(monkeypatch, tmp_path):
    result = _cli(monkeypatch, tmp_path, ["approvals", "--session", "auto"], global_mode="strict")
    assert result.exit_code == 0
    assert "Approval level (session override): auto" in plain(result.output)
    assert not (tmp_path / ".env").exists()

    # JSON output keeps headless/CI callers parseable.
    result = _cli(monkeypatch, tmp_path, ["approvals", "--session", "auto", "--json"], global_mode="strict")
    payload = json.loads(plain(result.output))
    assert payload["level"] == "auto"
    assert payload["source"] == "session override"
    assert payload["global"] == "strict"


def test_headless_help_explains_levels_and_usage(monkeypatch, tmp_path):
    result = _cli(monkeypatch, tmp_path, ["approvals", "--help"])
    assert result.exit_code == 0
    out = plain(result.output)

    assert "Usage: hobees approvals" in out
    # Every level is named *and* explained, not just listed.
    for level in APPROVAL_LEVELS:
        assert level in out
    for meaning in APPROVAL_LEVEL_MEANINGS.values():
        assert meaning.split()[0] in out
    assert "Approve / Edit / Reject" in out
    assert "persist globally" in out and "--session" in out and "--json" in out
    assert "Precedence:" in out

    # The alias spells the same help.
    alias = _cli(monkeypatch, tmp_path, ["permissions", "--help"])
    assert alias.exit_code == 0
    assert "Levels" in plain(alias.output) and "require_approval" in plain(alias.output)


def test_headless_permissions_alias_is_registered(monkeypatch, tmp_path):
    persisted = []
    monkeypatch.setattr(config, "set_global_approval_mode", lambda mode: persisted.append(mode))

    result = _cli(monkeypatch, tmp_path, ["permissions", "auto"])
    assert result.exit_code == 0
    assert persisted == ["auto"]

    commands = getattr(typer.main.get_command(main.app), "commands", {})
    assert "approvals" in commands and "permissions" in commands


def test_suggestions_are_words_the_handler_accepts(monkeypatch):
    _isolate(monkeypatch)
    # The catalog and the core resolver must agree on the vocabulary.
    assert set(APPROVAL_MODES) == set(APPROVAL_LEVELS)
    for catalog in (COMMANDS, TUI_COMMANDS):
        assert "approvals" in catalog and "permissions" in catalog
        for word in catalog["approvals"][1]:
            assert word in accepted_words(), f"{word!r} is suggested but not handled"

    # Every suggested word actually resolves.
    assert handle([], None)[0] == "status"
    assert handle(["show"], None)[0] == "status"
    for level in APPROVAL_LEVELS:
        assert handle([level], None)[0] == "ok"
    for word in (DEFAULT_WORD, CLEAR_WORD):
        assert handle([word], None)[0] == "ok"
    assert handle(["set", "auto"], None) == ("ok", "Session approval level set to 'auto'.", "auto")
    assert handle(["global", "auto"], None)[0] == "ok"
    assert handle(["show", "auto"], None)[0] == "error"


def test_status_report_includes_the_level_legend(monkeypatch):
    _isolate(monkeypatch)

    kind, message, level = handle([], None, interactive=True)
    assert kind == "status" and level is None
    assert "context default" in message
    # The meanings are printed too, so levels are explained without reading docs.
    assert "Approve / Edit / Reject" in message and "require_approval" in message
    for level_name in APPROVAL_LEVELS:
        assert level_name in message


def test_shell_handler_session_and_global(monkeypatch):
    _isolate(monkeypatch)
    persisted = []
    monkeypatch.setattr(config, "set_global_approval_mode", lambda mode: persisted.append(mode))

    state = {}
    shell._handle_approvals(["auto"], state)
    assert state["approval_mode"] == "auto"
    assert persisted == []

    shell._handle_approvals(["global", "strict"], state)
    assert persisted == ["strict"]
    assert state["approval_mode"] is None

    # The interactive alias dispatches to the same handler.
    assert shell._dispatch_command("permissions", ["pause"], "/permissions pause", "db", state) is False
    assert state["approval_mode"] == "pause"

    shell._handle_approvals(["nope"], state)
    assert state["approval_mode"] == "pause"

    shell._handle_approvals(["default"], state)
    assert state["approval_mode"] is None



def test_tui_handler_and_session_seed(monkeypatch):
    _isolate(monkeypatch)
    persisted = []
    monkeypatch.setattr(config, "set_global_approval_mode", lambda mode: persisted.append(mode))

    tui = HobeesTUI()
    asyncio.run(tui._handle_command("permissions", ["auto"]))
    assert tui.state.approval_mode == "auto"
    assert "Session approval level set to 'auto'." in tui.output_area.buffer.text

    asyncio.run(tui._handle_command("approvals", ["global", "strict"]))
    assert persisted == ["strict"]
    assert tui.state.approval_mode is None

    # A bad level is refused and the current state survives it.
    asyncio.run(tui._handle_command("approvals", ["nope"]))
    assert tui.state.approval_mode is None
    assert "Invalid approval level" in tui.output_area.buffer.text

    # `/thinking` still works — the approvals block used to swallow it.
    asyncio.run(tui._handle_command("thinking", ["low"]))
    assert tui.state.thinking_override == "low"

    tui._apply_session_context({"approval_mode": "pause"})
    assert tui.state.approval_mode == "pause"


def test_cli_session_flag_seeds_the_shell_state(monkeypatch):
    monkeypatch.setattr(config.settings, "config_path", None)
    monkeypatch.setattr(config.settings, "database_url", "sqlite:///:memory:")

    captured = {}
    monkeypatch.setattr(shell, "_shell_loop", lambda ctx, provider: captured.update(ctx))

    main.shell_cmd(hive="alpha", approval_mode="auto", auto_approve=False)
    assert captured["active_hive"] == "alpha"
    assert captured["approval_mode"] == "auto"

    captured.clear()
    main.shell_cmd(hive=None, approval_mode=None, auto_approve=True)
    assert captured["approval_mode"] == "auto"

    try:
        main.shell_cmd(hive=None, approval_mode="nope", auto_approve=False)
    except Exception as exc:  # typer.Exit
        assert getattr(exc, "exit_code", None) == 1
    else:
        raise AssertionError("an invalid --approval-mode must exit non-zero")


def test_shell_goal_passes_the_session_level_to_the_graph(monkeypatch, tmp_path):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from hobees.db import session as db_session
    from hobees.db.models import Base, Bee, LLMProvider

    engine = create_engine(f"sqlite:///{tmp_path / 'goal.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(
        db_session,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    with db_session.session_scope() as session:
        provider = LLMProvider(
            alias="goal-provider",
            provider_type="openai",
            api_key_env="NONE",
            default_model="m",
            input_cost_per_1m=0.0,
            output_cost_per_1m=0.0,
        )
        session.add(provider)
        session.flush()
        session.add(
            Bee(
                name="goal-bee",
                role_description="Test worker",
                system_prompt="You are a test worker.",
                provider_id=provider.id,
                model_name="m",
                tool_names=[],
            )
        )
        session.commit()
        provider_id = provider.id

    monkeypatch.setattr(shell.Prompt, "ask", lambda *_args, **_kwargs: "")

    captured = {}

    @contextmanager
    def fake_hive_app(*args, **kwargs):
        captured["kwargs"] = kwargs
        yield Mock(invoke=lambda *_a, **_k: {"messages": [AIMessage(content="done")]})

    monkeypatch.setattr(shell, "hive_app", fake_hive_app)
    monkeypatch.setattr(shell, "build_queen", lambda *_a, **_k: object())
    monkeypatch.setattr(shell, "_show_telemetry_footer", lambda *_a: None)
    monkeypatch.setattr(shell, "_check_skill_draft", lambda *_a: None)
    monkeypatch.setattr("hobees.core.memory_manager.extract_run_memories", lambda **_kw: None)
    monkeypatch.setattr("hobees.core.skill_harvester.harvest_completed_run", lambda *_a: None)

    with db_session.session_scope() as session:
        provider = session.get(LLMProvider, provider_id)

    state = {"approval_mode": "strict", "thinking_override": "auto"}
    shell._handle_goal(["do", "the", "thing"], provider, str(engine.url), state)
    assert captured["kwargs"]["approval_mode"] == "strict"
    engine.dispose()


def test_saved_session_carries_the_level(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "_SESSION_DIR", tmp_path)
    state = shell._capture_session_state("alpha", "thread-1", "auto")
    assert state["approval_mode"] == "auto"
    shell._save_session("s1", state)
    assert shell._load_session("s1")["approval_mode"] == "auto"

    shell_state = {"approval_mode": "pause"}
    shell._handle_session(["save", "s2"], shell_state)
    assert shell._load_session("s2")["approval_mode"] == "pause"

    fresh = {}
    shell._handle_session(["load", "s2"], fresh)
    assert fresh["approval_mode"] == "pause"
