from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hobees.cli import main, shell
from hobees.db import session as db_session
from hobees.db.models import Base, Bee, LLMProvider, Run
from hobees.db.session import session_scope


def _setup_database(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(
        db_session,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    with session_scope() as session:
        provider = LLMProvider(
            alias="run-test-provider",
            provider_type="openai",
            api_key_env="NONE",
            default_model="test-model",
        )
        session.add(provider)
        session.flush()
        bee = Bee(
            name="run-test-bee",
            role_description="Test worker",
            system_prompt="You are a test worker.",
            provider_id=provider.id,
            model_name="test-model",
            tool_names=[],
        )
        session.add(bee)
        session.flush()
        provider_id = provider.id

    return engine, provider_id


@contextmanager
def _completed_hive_app(*_args, **_kwargs):
    class App:
        def invoke(self, *_invoke_args, **_invoke_kwargs):
            return {"messages": [AIMessage(content="Goal completed")]}

    yield App()


def test_prompt_sets_completed_at(monkeypatch, tmp_path):
    engine, _ = _setup_database(monkeypatch, tmp_path)
    try:
        with (
            patch("hobees.core.hive_builder.hive_app", _completed_hive_app),
            patch("hobees.core.memory_manager.extract_run_memories"),
        ):
            main.prompt(
                goal="Complete a test task",
                provider="run-test-provider",
                model="test-model",
                thinking="off",
            )

        with session_scope() as session:
            run = session.query(Run).one()
            assert run.status == "completed"
            assert run.completed_at is not None
    finally:
        engine.dispose()


def test_shell_goal_sets_completed_at(monkeypatch, tmp_path):
    engine, provider_id = _setup_database(monkeypatch, tmp_path)
    try:
        with session_scope() as session:
            provider = session.get(LLMProvider, provider_id)

        monkeypatch.setattr(shell.Prompt, "ask", lambda *_args, **_kwargs: "run-test-bee")
        monkeypatch.setattr(
            LLMProvider,
            "query",
            SimpleNamespace(all=lambda: [provider]),
            raising=False,
        )
        monkeypatch.setattr(shell, "build_queen", lambda *_args, **_kwargs: object())
        monkeypatch.setattr(shell, "hive_app", _completed_hive_app)
        monkeypatch.setattr(shell, "_show_telemetry_footer", lambda *_args: None)
        monkeypatch.setattr(shell, "_check_skill_draft", lambda *_args: None)

        with patch("hobees.core.memory_manager.extract_run_memories"):
            state = {}
            shell._handle_goal(
                ["Complete", "a", "shell", "task"],
                provider,
                engine.url,
                state,
            )

        with session_scope() as session:
            run = session.query(Run).filter_by(thread_id=state["thread_id"]).one()
            assert run.status == "completed"
            assert run.completed_at is not None
    finally:
        engine.dispose()
