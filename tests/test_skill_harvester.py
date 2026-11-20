import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hobees.cli import main as main_cli
from hobees.cli import shell
from hobees.core import skill_harvester
from hobees.db import session as db_session
from hobees.db.models import Base, Bee, Hive, HiveMembership, LLMProvider, Run, UsageEvent
from hobees.db.session import session_scope


def _setup_run(monkeypatch, tmp_path, tool_calls):
    engine = create_engine(f"sqlite:///{tmp_path / 'harvester.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(
        db_session,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    with session_scope() as session:
        provider = LLMProvider(
            alias="harvester-provider",
            provider_type="openai",
            api_key_env="NONE",
            default_model="test-model",
        )
        session.add(provider)
        session.flush()
        hive = Hive(
            name="harvester-hive",
            supervisor_provider_id=provider.id,
            supervisor_model_name="test-model",
            is_dynamic=False,
        )
        session.add(hive)
        session.flush()
        run = Run(
            thread_id="harvester-thread",
            hive_id=hive.id,
            mode="targeted",
            goal="Complete a reusable workflow",
            status="completed",
        )
        session.add(run)
        session.flush()
        session.add(
            UsageEvent(
                run_id=run.id,
                thread_id=run.thread_id,
                bee_name="worker",
                provider_alias=provider.alias,
                model_name="test-model",
                tool_calls=tool_calls,
            )
        )
        run_id = run.id

    return engine, run_id


def _setup_cli_db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cli-harvester.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(
        db_session,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    with session_scope() as session:
        provider = LLMProvider(
            alias="cli-provider",
            provider_type="openai",
            api_key_env="NONE",
            default_model="test-model",
        )
        session.add(provider)
        session.flush()
        bee = Bee(
            name="cli-worker",
            role_description="Test worker",
            system_prompt="Test prompt",
            provider_id=provider.id,
            model_name="test-model",
            tool_names=[],
        )
        session.add(bee)
        provider_id = provider.id

    return engine, provider_id


class _SyncHiveContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def invoke(self, *_args, **_kwargs):
        return {"messages": [SimpleNamespace(content="Goal completed")]}


def test_harvest_completed_run_uses_supervisor_provider_and_saves_draft(
    monkeypatch, tmp_path
):
    engine, run_id = _setup_run(
        monkeypatch, tmp_path, ["read_file", "list_directory", "read_file", "write_file"]
    )
    draft = {
        "name": "review-project-files",
        "description": "Review a project's key files",
        "instructions": "Read the project files, then summarize their structure.",
        "tags": ["review"],
        "bee_names": ["worker"],
    }
    calls = []

    class Model:
        def invoke(self, prompt):
            assert "Complete a reusable workflow" in prompt
            return SimpleNamespace(content=json.dumps(draft))

    def fake_get_chat_model(provider, model_name, temperature):
        calls.append((provider.alias, model_name, temperature))
        return Model()

    monkeypatch.setattr(skill_harvester, "get_chat_model", fake_get_chat_model)
    try:
        assert skill_harvester.harvest_completed_run(run_id) == draft
        assert calls == [("harvester-provider", "test-model", 0.3)]

        with session_scope() as session:
            run = session.get(Run, run_id)
            assert run.suggested_skill_draft == draft

        assert skill_harvester.harvest_completed_run(run_id) == draft
        assert len(calls) == 1
    finally:
        engine.dispose()


def test_harvest_skips_runs_below_tool_call_threshold(monkeypatch, tmp_path):
    engine, run_id = _setup_run(
        monkeypatch, tmp_path, ["read_file", "list_directory", "write_file"]
    )

    def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("unexpected model call")

    monkeypatch.setattr(
        skill_harvester,
        "get_chat_model",
        unexpected_model_call,
    )
    try:
        assert skill_harvester.harvest_completed_run(run_id) is None
    finally:
        engine.dispose()


def test_one_shot_prompt_harvests_completed_run(monkeypatch, tmp_path):
    engine, _provider_id = _setup_cli_db(monkeypatch, tmp_path)
    hive_app_calls = []
    harvested_run_ids = []
    monkeypatch.setattr(
        "hobees.core.hive_builder.hive_app",
        lambda *args: hive_app_calls.append(args) or _SyncHiveContext(),
    )
    monkeypatch.setattr(
        "hobees.core.memory_manager.extract_run_memories",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        skill_harvester,
        "harvest_completed_run",
        lambda run_id: harvested_run_ids.append(run_id),
    )

    try:
        main_cli.prompt("Run a one-shot task", "cli-provider", "test-model", "off")

        with session_scope() as session:
            run = session.query(Run).filter_by(goal="Run a one-shot task").one()
            assert run.status == "completed"
            assert run.completed_at is not None
            assert hive_app_calls[0][5] == run.id
            assert harvested_run_ids == [run.id]
    finally:
        engine.dispose()


def test_shell_goal_harvests_completed_run(monkeypatch, tmp_path):
    engine, provider_id = _setup_cli_db(monkeypatch, tmp_path)
    hive_app_calls = []
    harvested_run_ids = []
    monkeypatch.setattr(shell.Prompt, "ask", lambda *_args, **_kwargs: "cli-worker")
    monkeypatch.setattr(
        shell,
        "hive_app",
        lambda *args: hive_app_calls.append(args) or _SyncHiveContext(),
    )
    monkeypatch.setattr(
        "hobees.core.memory_manager.extract_run_memories",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(shell, "build_queen", lambda *_args: object())
    monkeypatch.setattr(shell, "_show_telemetry_footer", lambda *_args: None)
    monkeypatch.setattr(shell, "_check_skill_draft", lambda *_args: None)
    monkeypatch.setattr(
        skill_harvester,
        "harvest_completed_run",
        lambda run_id: harvested_run_ids.append(run_id),
    )

    try:
        with session_scope() as session:
            provider = session.get(LLMProvider, provider_id)

        shell._handle_goal(["Run", "a", "shell", "goal"], provider, str(engine.url), {})

        with session_scope() as session:
            run = session.query(Run).filter_by(goal="Run a shell goal").one()
            assert run.status == "completed"
            assert run.completed_at is not None
            assert hive_app_calls[0][5] == run.id
            assert harvested_run_ids == [run.id]
    finally:
        engine.dispose()


def test_shell_hive_chat_harvests_the_completed_session(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'interactive.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(
        db_session,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    with session_scope() as session:
        provider = LLMProvider(
            alias="interactive-provider",
            provider_type="openai",
            api_key_env="NONE",
            default_model="test-model",
        )
        session.add(provider)
        session.flush()
        bee = Bee(
            name="interactive-worker",
            role_description="Test worker",
            system_prompt="Test prompt",
            provider_id=provider.id,
            model_name="test-model",
            tool_names=[],
        )
        session.add(bee)
        session.flush()
        hive = Hive(
            name="interactive-hive",
            supervisor_provider_id=provider.id,
            supervisor_model_name="test-model",
            is_dynamic=False,
        )
        session.add(hive)
        session.flush()
        session.add(HiveMembership(hive_id=hive.id, bee_id=bee.id))
        hive_id = hive.id
        provider_id = provider.id

    class AsyncContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return False

    class Live:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def update(self, *_args, **_kwargs):
            pass

    hive_app_calls = []
    harvested_run_ids = []
    monkeypatch.setattr(
        "hobees.core.hive_builder.hive_app_async",
        lambda *args, **kwargs: hive_app_calls.append((args, kwargs)) or AsyncContext(),
    )
    monkeypatch.setattr("rich.live.Live", Live)
    monkeypatch.setattr(shell.console, "input", lambda *_args, **_kwargs: "exit")
    monkeypatch.setattr(
        skill_harvester,
        "harvest_completed_run",
        lambda run_id: harvested_run_ids.append(run_id),
    )
    monkeypatch.setattr(shell, "_check_skill_draft", lambda *_args: None)

    try:
        with session_scope() as session:
            provider = session.get(LLMProvider, provider_id)

        asyncio.run(
            shell._chat_with_hive(
                "interactive-hive",
                provider,
                str(engine.url),
                {},
            )
        )

        with session_scope() as session:
            run = session.query(Run).filter_by(hive_id=hive_id).one()
            assert run.status == "completed"
            assert run.completed_at is not None
            assert hive_app_calls[0][0][5] == run.id
            assert harvested_run_ids == [run.id]
    finally:
        engine.dispose()
