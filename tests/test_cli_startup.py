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


def test_stdin_escape_listener_uses_msvcrt_on_windows(monkeypatch):
    msvcrt = SimpleNamespace(kbhit=lambda: True, getwch=lambda: "\x1b")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
    cancel_flag = {"cancelled": False}

    asyncio.run(shell._stdin_escape_listener(cancel_flag))

    assert cancel_flag["cancelled"] is True
