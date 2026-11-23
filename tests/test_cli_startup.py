import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from hobees.cli import main
from hobees.cli import shell


def test_root_auto_syncs_config_before_subcommand(monkeypatch, tmp_path):
    config_path = tmp_path / "hobees.json"
    monkeypatch.setattr("hobees.config.settings.config_path", config_path)
    sync = Mock()
    monkeypatch.setattr(main, "_sync_startup_config", sync)
    context = SimpleNamespace(
        resilient_parsing=False,
        invoked_subcommand="hive",
    )

    main._root(context)

    sync.assert_called_once_with(config_path)


def test_root_does_not_auto_sync_for_init(monkeypatch, tmp_path):
    from hobees import config

    config_path = tmp_path / "hobees.json"
    monkeypatch.setattr(config.settings, "config_path", config_path)
    monkeypatch.setattr(config.settings, "database_url", "sqlite:///:memory:")
    sync = Mock()
    monkeypatch.setattr(main, "_sync_startup_config", sync)
    context = SimpleNamespace(
        resilient_parsing=False,
        invoked_subcommand="init",
    )

    main._root(context)

    sync.assert_not_called()


def test_root_creates_default_database_url_when_unconfigured(monkeypatch, tmp_path, capsys):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from hobees import config

    config_dir = tmp_path / ".hobees"
    monkeypatch.setattr(config, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(config.settings, "database_url", None)
    context = SimpleNamespace(resilient_parsing=False, invoked_subcommand="init")

    main._root(context)

    note = capsys.readouterr().out
    assert ".hobees" in note
    assert "hobees.db" in note
    assert make_url(config.settings.database_url).database == str(
        config_dir / "hobees.db"
    )
    assert (config_dir / ".env").read_text(encoding="utf-8") == (
        f"HOBEES_DATABASE_URL={config.settings.database_url}\n"
    )
    engine = create_engine(config.settings.database_url)
    try:
        with engine.connect():
            pass
    finally:
        engine.dispose()
    assert (config_dir / "hobees.db").is_file()


def test_root_upgrades_legacy_default_database_url(monkeypatch, tmp_path, capsys):
    from sqlalchemy.engine import make_url

    from hobees import config

    config_dir = tmp_path / ".hobees"
    config_dir.mkdir()
    (config_dir / ".env").write_text(
        "HOBEES_DATABASE_URL=sqlite:///hobees.db\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(config.settings, "database_url", "sqlite:///hobees.db")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HOBEES_DATABASE_URL", raising=False)
    context = SimpleNamespace(resilient_parsing=False, invoked_subcommand="init")

    main._root(context)

    assert make_url(config.settings.database_url).database == str(
        config_dir / "hobees.db"
    )
    note = capsys.readouterr().out
    assert ".hobees" in note
    assert "hobees.db" in note


def test_root_preserves_configured_database_url(monkeypatch, tmp_path):
    from hobees import config

    env_path = tmp_path / ".hobees" / ".env"
    env_path.parent.mkdir()
    env_path.write_text("HOBEES_DATABASE_URL=postgresql://db/hobees\n", encoding="utf-8")
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path / ".hobees")
    monkeypatch.setattr(config.settings, "database_url", "postgresql://db/hobees")
    context = SimpleNamespace(resilient_parsing=False, invoked_subcommand="init")

    main._root(context)

    assert config.settings.database_url == "postgresql://db/hobees"
    assert env_path.read_text(encoding="utf-8") == "HOBEES_DATABASE_URL=postgresql://db/hobees\n"


def test_ensure_database_initialized_creates_schema_for_empty_database():
    from sqlalchemy import create_engine, inspect

    from hobees.cli.main import _ensure_database_initialized

    engine = create_engine("sqlite:///:memory:")
    try:
        _ensure_database_initialized(engine)

        assert "llm_providers" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_provider_detection_gate_runs_only_for_first_launch_without_providers(monkeypatch):
    detector = Mock(return_value=True)
    run_detection = Mock()
    monkeypatch.setattr("hobees.core.provider_detector.is_first_launch", detector)
    monkeypatch.setattr(main, "_run_provider_detection", run_detection)

    assert main._run_provider_detection_if_needed([]) is True
    run_detection.assert_called_once_with()

    run_detection.reset_mock()
    detector.reset_mock()
    detector.return_value = False
    assert main._run_provider_detection_if_needed([]) is False
    run_detection.assert_not_called()
    detector.assert_called_once()


def test_provider_detection_gate_skips_when_providers_exist(monkeypatch):
    detector = Mock()
    run_detection = Mock()
    monkeypatch.setattr("hobees.core.provider_detector.is_first_launch", detector)
    monkeypatch.setattr(main, "_run_provider_detection", run_detection)

    assert main._run_provider_detection_if_needed([object()]) is False
    detector.assert_not_called()
    run_detection.assert_not_called()


def test_detect_providers_cli_command_runs_detection(monkeypatch):
    from typer.testing import CliRunner

    run_detection = Mock()
    monkeypatch.setattr(main, "_run_provider_detection", run_detection)
    monkeypatch.setattr(main, "_ensure_database_initialized", Mock())
    monkeypatch.setattr("hobees.db.session.get_engine", Mock())

    result = CliRunner().invoke(main.app, ["detect-providers"])

    assert result.exit_code == 0, result.output
    run_detection.assert_called_once_with()


def test_provider_detection_skips_registered_candidates(monkeypatch):
    from io import StringIO
    from types import SimpleNamespace

    from rich.console import Console

    from hobees.core import provider_detector

    existing = {"alias": "openai-main", "provider_type": "openai", "source_label": "env"}
    new = {"alias": "local-new", "provider_type": "openai_compatible", "source_label": "local"}
    output = StringIO()
    register = Mock(return_value=["local-new"])

    monkeypatch.setattr(main, "console", Console(file=output, force_terminal=False))
    monkeypatch.setattr(provider_detector, "detect_available_providers", lambda: [existing, new])
    monkeypatch.setattr(provider_detector, "get_registered_provider_aliases", lambda: {"openai-main"})
    monkeypatch.setattr(provider_detector, "auto_register_providers", register)
    monkeypatch.setattr(provider_detector, "mark_detected", Mock())
    monkeypatch.setattr(main.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    main._run_provider_detection()

    text = output.getvalue()
    assert "No providers found" not in text
    assert "Already registered; skipping: openai-main" in text
    assert text.count("openai-main") == 1
    assert "local-new" in text
    register.assert_called_once_with([new])


def test_provider_detection_reports_when_all_candidates_are_registered(monkeypatch):
    from io import StringIO

    from rich.console import Console

    from hobees.core import provider_detector

    candidate = {"alias": "openai-main", "provider_type": "openai", "source_label": "env"}
    output = StringIO()
    register = Mock()

    monkeypatch.setattr(main, "console", Console(file=output, force_terminal=False))
    monkeypatch.setattr(provider_detector, "detect_available_providers", lambda: [candidate])
    monkeypatch.setattr(provider_detector, "get_registered_provider_aliases", lambda: {"openai-main"})
    monkeypatch.setattr(provider_detector, "auto_register_providers", register)
    monkeypatch.setattr(provider_detector, "mark_detected", Mock())

    main._run_provider_detection()

    text = output.getvalue()
    assert "All detected providers are already registered" in text
    assert "Detected Providers" not in text
    register.assert_not_called()


def test_shell_routes_unprefixed_input_to_active_hive(monkeypatch):
    chat = Mock()
    async def fake_chat(hive_name, provider, db_url, state, initial_input=None):
        chat(hive_name, provider, db_url, state, initial_input)

    monkeypatch.setattr(shell, "_chat_with_hive", fake_chat)
    state = {"active_hive": "dev-team", "provider": object()}

    shell._dispatch_command(
        "implement",
        ["feature"],
        "implement feature",
        "sqlite:///:memory:",
        state,
    )

    chat.assert_called_once_with(
        "dev-team",
        state["provider"],
        "sqlite:///:memory:",
        state,
        "implement feature",
    )


def test_shell_routes_repeated_unprefixed_input_with_persistent_loop(monkeypatch):
    received = []

    async def fake_chat(provider, db_url, state, initial_input=None):
        import asyncio

        queue = asyncio.Queue()
        queue.put_nowait(initial_input)
        received.append((await queue.get(), asyncio.get_running_loop()))

    monkeypatch.setattr(
        shell,
        "_chat_with_assistant",
        lambda user_input, provider, db_url, state: fake_chat(
            provider, db_url, state, initial_input=user_input
        ),
    )
    state = {"provider": object()}

    shell._dispatch_command(
        "first",
        [],
        "first",
        "sqlite:///:memory:",
        state,
    )
    shell._dispatch_command(
        "second",
        [],
        "second",
        "sqlite:///:memory:",
        state,
    )

    assert [item[0] for item in received] == ["first", "second"]
    assert received[0][1] is received[1][1]
    shell._stop_shell_chat_loop(state)


def test_shell_dispatches_detect_providers_slash_command(monkeypatch):
    detection = Mock()
    monkeypatch.setattr(main, "_run_provider_detection", detection)

    should_exit = shell._dispatch_command(
        "detect_providers",
        [],
        "/detect_providers",
        "sqlite:///:memory:",
        {},
    )

    assert should_exit is False
    detection.assert_called_once_with()


def test_stdin_escape_listener_uses_msvcrt_on_windows(monkeypatch):
    msvcrt = SimpleNamespace(kbhit=lambda: True, getwch=lambda: "\x1b")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
    cancel_flag = {"cancelled": False}

    asyncio.run(shell._stdin_escape_listener(cancel_flag))

    assert cancel_flag["cancelled"] is True
