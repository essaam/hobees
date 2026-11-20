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
    config_path = tmp_path / "hobees.json"
    monkeypatch.setattr("hobees.config.settings.config_path", config_path)
    sync = Mock()
    monkeypatch.setattr(main, "_sync_startup_config", sync)
    context = SimpleNamespace(
        resilient_parsing=False,
        invoked_subcommand="init",
    )

    main._root(context)

    sync.assert_not_called()


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
