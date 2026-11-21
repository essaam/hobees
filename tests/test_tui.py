import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import hobees.cli.tui as tui_module
from hobees.cli.tui import HobeesTUI
from hobees.cli.hive_cmd import get_hive_artifacts_dir
from prompt_toolkit.output import DummyOutput


def test_tui_renders_warning_and_success_output():
    tui = HobeesTUI()

    tui._add_output("warn", "No artifacts found")
    tui._add_output("success", "Hive completed")

    assert "No artifacts found" in tui.output_area.buffer.text
    assert "Hive completed" in tui.output_area.buffer.text
    assert tui._output_lexer.lex_document(tui.output_area.buffer.document)(0)[0][0] == (
        "class:output.warn"
    )
    assert tui._output_lexer.lex_document(tui.output_area.buffer.document)(1)[0][0] == (
        "class:output.success"
    )


def test_tui_leaves_mouse_selection_available_to_terminal():
    tui = HobeesTUI()
    app = tui._create_application(output=DummyOutput())

    assert not app.mouse_support()
    assert tui.output_area.control.is_focusable()
    assert tui.output_area.buffer.read_only()


def test_tui_routes_initial_text_to_active_hive(monkeypatch):
    tui = HobeesTUI()
    tui.state.active_hive = "dev-team"
    received = []

    async def start_hive(name):
        assert name == "dev-team"
        tui.state.chat_hive_data = (object(),)

    async def handle_input(text):
        received.append(text)

    monkeypatch.setattr(tui, "_start_hive_chat", start_hive)
    monkeypatch.setattr(tui, "_handle_chat_input", handle_input)

    asyncio.run(tui._process_input("implement feature"))

    assert received == ["implement feature"]


def test_tui_hive_turn_uses_run_id_for_telemetry(monkeypatch):
    tui = HobeesTUI()
    run_id = 42
    tui.state.chat_hive_data = (
        SimpleNamespace(name="alpha"),
        [],
        {},
        "thread-alpha",
        "medium",
        run_id,
        [],
    )
    calls = []

    class AsyncContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        "hobees.core.hive_builder.hive_app_async",
        lambda *args: calls.append(args) or AsyncContext(),
    )
    monkeypatch.setattr(
        tui,
        "_stream_into_buffer",
        lambda *_args, **_kwargs: asyncio.sleep(0),
    )
    monkeypatch.setattr("hobees.db.analytics.run_thread_usage", lambda *_args: None)

    asyncio.run(tui._stream_hive_response("Do the work"))

    assert calls[0][5] == run_id


def test_tui_hive_chat_completion_harvests_skill_draft(monkeypatch):
    tui = HobeesTUI()
    run = SimpleNamespace(
        id=42,
        goal="old goal",
        status="running",
        completed_at=None,
    )
    saved_run_ids = []
    draft = {"name": "tui-skill"}

    class Session:
        def get(self, model, run_id):
            assert model.__name__ == "Run"
            assert run_id == run.id
            return run

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr("hobees.db.session.session_scope", fake_session_scope)
    monkeypatch.setattr(
        "hobees.core.skill_harvester.harvest_completed_run",
        lambda run_id: saved_run_ids.append(run_id) or draft,
    )
    monkeypatch.setattr(tui, "_build_layout", lambda: None)
    tui.app = SimpleNamespace(invalidate=lambda: None)
    tui.state.chat_mode = True
    tui.state.chat_hive_data = (
        SimpleNamespace(name="alpha"),
        [],
        {},
        "thread-alpha",
        "medium",
        run.id,
        ["First task", "Follow-up task"],
    )

    asyncio.run(tui._exit_chat())

    assert run.goal == "First task\nFollow-up task"
    assert run.status == "completed"
    assert run.completed_at is not None
    assert saved_run_ids == [run.id]
    assert "tui-skill" in tui.output_area.buffer.text


def test_tui_hive_list_displays_empty_state(monkeypatch):
    class Query:
        def order_by(self, *_):
            return self

        def all(self):
            return []

    class Session:
        def query(self, *_):
            return Query()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(tui_module, "session_scope", fake_session_scope)
    tui = HobeesTUI()

    asyncio.run(tui._list_hives())

    assert "No Hives registered" in tui.output_area.buffer.text


def test_tui_removes_multiple_hives_by_number(monkeypatch):
    removed = []

    monkeypatch.setattr(
        "hobees.cli.hive_cmd.get_hive_names",
        lambda: ["alpha", "beta", "gamma"],
    )
    monkeypatch.setattr(
        "hobees.cli.hive_cmd.remove_hives",
        lambda names: removed.extend(names) or names,
    )
    tui = HobeesTUI()
    tui.state.active_hive = "gamma"
    tui.state.chat_hive_data = (SimpleNamespace(name="gamma"),)

    answers = iter(("1,3", "yes"))

    async def answer(prompt):
        if "Hive numbers" in prompt:
            assert "Hive numbers to remove" in prompt
        else:
            assert "alpha, gamma" in prompt
        return next(answers)

    monkeypatch.setattr(tui, "_prompt_input", answer)
    asyncio.run(tui._remove_hives([]))

    assert removed == ["alpha", "gamma"]
    assert tui.state.active_hive is None
    assert tui.state.chat_hive_data is None
    assert "Hive 'alpha' removed." in tui.output_area.buffer.text


def test_hive_artifact_directory_prefers_project_path(monkeypatch, tmp_path):
    class Query:
        def filter_by(self, **_):
            return self

        def first(self):
            return SimpleNamespace(project_path=str(tmp_path))

    class Session:
        def query(self, *_):
            return Query()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr("hobees.db.session.session_scope", fake_session_scope)

    assert get_hive_artifacts_dir("team") == tmp_path
