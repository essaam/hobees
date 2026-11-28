from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from hobees.cli.main import _run_migrations
from hobees.cli.shell import _get_async_checkpointer, _get_checkpointer
from hobees.db.backends import get_database_backend, get_postgres_checkpoint_url


class CheckpointState(TypedDict):
    value: str


def _checkpoint_graph(saver):
    graph = StateGraph(CheckpointState)
    graph.add_node("preserve", lambda _state: {})
    graph.add_edge(START, "preserve")
    graph.add_edge("preserve", END)
    return graph.compile(checkpointer=saver)


def test_database_backend_selection_and_validation():
    assert get_database_backend("sqlite:///./hobees.db") == "sqlite"
    assert (
        get_database_backend("postgresql+psycopg://user:pass@localhost/hobees")
        == "postgresql"
    )
    assert (
        get_postgres_checkpoint_url(
            "postgresql+psycopg://user:pass@localhost/hobees"
        )
        == "postgresql://user:pass@localhost/hobees"
    )

    with pytest.raises(ValueError, match="Unsupported database URL scheme"):
        get_database_backend("mysql://user:pass@localhost/hobees")


def test_urls_reach_the_checkpointer_with_the_password_intact():
    """The reported failure: SQLAlchemy connects with the URL object while a run that
    stringifies it first authenticates with the mask, so Postgres answers
    `password authentication failed` for a password nobody wrote.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from hobees.db.backends import MASKED_PASSWORD, render_db_url

    raw = "postgresql+psycopg://hobees:secretpass@localhost:5432/hobeesdb"
    engine = create_engine(raw)  # building an engine connects nothing
    url = engine.url

    assert url.password == "secretpass"
    assert str(url) == "postgresql+psycopg://hobees:***@localhost:5432/hobeesdb"
    assert MASKED_PASSWORD in str(url)

    # A string and a URL object must give the same psycopg connection string.
    assert get_postgres_checkpoint_url(raw) == "postgresql://hobees:secretpass@localhost:5432/hobeesdb"
    assert get_postgres_checkpoint_url(url) == "postgresql://hobees:secretpass@localhost:5432/hobeesdb"
    assert render_db_url(raw) == raw
    assert render_db_url(url) == raw
    assert get_database_backend(url) == "postgresql"

    # The session path is the same object: session.bind.url keeps the password.
    session = sessionmaker(bind=engine, autoflush=False)()
    assert session.bind.url.password == "secretpass"
    assert "secretpass" in get_postgres_checkpoint_url(session.bind.url)
    session.close()

    # A URL that already lost its password cannot be recovered: the mask is the password by
    # then, so the run reports where it was lost instead of connecting with ***.
    for masked in (str(url), f"{url}", make_url(str(url))):
        with pytest.raises(ValueError, match="masked password"):
            get_postgres_checkpoint_url(masked)
        with pytest.raises(ValueError, match="masked password"):
            render_db_url(masked)


def test_no_execution_path_stringifies_the_database_url():
    """A URL reaches a connection as an object, never as text: str()/f-string masks the
    password and the mask then becomes the password sent to the server. These are the paths
    that build a checkpointer, so they must render the URL instead of stringifying it."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "hobees"
    names = [
        "core/hive_builder.py",
        "core/queen.py",
        "cli/shell.py",
        "cli/main.py",
        "cli/hive_cmd.py",
        "cli/tui.py",
        "api/app.py",
        "web/app.py",
        "db/backends.py",
    ]
    offenders = []
    pattern = re.compile(r"(?:str\(|f\"[^\"]*\{)(get_engine\(\)\.url|engine\.url|session\.bind\.url|db_url)")
    for name in names:
        path = src / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#"):
                continue  # the rule, written as a comment
            match = pattern.search(line)
            if match:
                offenders.append(f"{name}:{line.strip()}")

    assert not offenders
    checkpointer_source = (src / "db/backends.py").read_text(encoding="utf-8")
    assert "hide_password=False" in checkpointer_source
    assert "render_db_url(db_url)" in (src / "core/hive_builder.py").read_text(encoding="utf-8")


def test_shared_engine_accepts_sqlite_url(monkeypatch):
    from hobees.config import settings
    from hobees.db import session as db_session

    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_SessionLocal", None)

    engine = db_session.get_engine()
    try:
        assert engine.dialect.name == "sqlite"
    finally:
        engine.dispose()


def test_shared_engine_rejects_unsupported_url(monkeypatch):
    from hobees.config import settings
    from hobees.db import session as db_session

    monkeypatch.setattr(settings, "database_url", "mysql://user:pass@localhost/hobees")
    monkeypatch.setattr(db_session, "_engine", None)

    with pytest.raises(ValueError, match="Unsupported database URL scheme"):
        db_session.get_engine()


def test_memory_sqlite_uses_ephemeral_checkpointer():
    saver, connection = _get_checkpointer("sqlite:///:memory:")

    assert isinstance(saver, MemorySaver)
    assert connection is None


def test_file_sqlite_chat_checkpoints_persist_between_connections(tmp_path):
    db_path = tmp_path / "chat-checkpoints.sqlite"
    db_url = f"sqlite:///{db_path}"
    config = {"configurable": {"thread_id": "persistent-chat"}}

    saver, connection = _get_checkpointer(db_url)
    try:
        _checkpoint_graph(saver).invoke({"value": "saved"}, config=config)
    finally:
        connection.close()

    saver, connection = _get_checkpointer(db_url)
    try:
        state = _checkpoint_graph(saver).get_state(config)
    finally:
        connection.close()

    assert isinstance(saver, SqliteSaver)
    assert state.values == {"value": "saved"}


def test_file_sqlite_async_chat_checkpointer_streams_and_persists(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'async-chat-checkpoints.sqlite'}"
    config = {"configurable": {"thread_id": "persistent-async-chat"}}

    async def verify_async_checkpointer():
        saver, stack = await _get_async_checkpointer(db_url)
        try:
            await _checkpoint_graph(saver).ainvoke({"value": "saved"}, config=config)
        finally:
            await stack.aclose()

        saver, stack = await _get_async_checkpointer(db_url)
        try:
            state = await _checkpoint_graph(saver).aget_state(config)
        finally:
            await stack.aclose()
        return saver, state

    saver, state = asyncio.run(verify_async_checkpointer())

    assert isinstance(saver, AsyncSqliteSaver)
    assert state.values == {"value": "saved"}


def test_sqlite_migrations_create_json_columns_and_are_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE llm_providers (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE bees (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE hives (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE runs (id INTEGER PRIMARY KEY)"))

        _run_migrations(engine)
        _run_migrations(engine)

        provider_columns = {
            column["name"]: column["type"]
            for column in inspect(engine).get_columns("llm_providers")
        }
        run_columns = {
            column["name"]: column["type"]
            for column in inspect(engine).get_columns("runs")
        }
        assert str(provider_columns["available_models"]).upper() == "JSON"
        assert str(run_columns["suggested_skill_draft"]).upper() == "JSON"
    finally:
        engine.dispose()


POSTGRES_TEST_URL = os.environ.get("HOBEES_TEST_POSTGRES_URL")


@pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="Set HOBEES_TEST_POSTGRES_URL to a disposable PostgreSQL database",
)
def test_postgres_migrations_and_checkpoints():
    assert POSTGRES_TEST_URL is not None
    schema = f"hobees_test_{uuid.uuid4().hex}"
    base_url = make_url(POSTGRES_TEST_URL)
    admin_engine = create_engine(base_url)

    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    test_url = base_url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(test_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE llm_providers "
                    "(id INTEGER PRIMARY KEY, available_models TEXT DEFAULT '[]')"
                )
            )
            connection.execute(text("CREATE TABLE bees (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE hives (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE runs "
                    "(id INTEGER PRIMARY KEY, suggested_skill_draft TEXT)"
                )
            )
            connection.execute(
                text("INSERT INTO llm_providers VALUES (1, '[\"model-a\"]')")
            )
            connection.execute(
                text("INSERT INTO runs VALUES (1, '{\"name\":\"draft\"}')")
            )

        _run_migrations(engine)
        _run_migrations(engine)

        provider_columns = {
            column["name"]: column["type"]
            for column in inspect(engine).get_columns("llm_providers")
        }
        run_columns = {
            column["name"]: column["type"]
            for column in inspect(engine).get_columns("runs")
        }
        assert str(provider_columns["available_models"]).upper() == "JSON"
        assert str(run_columns["suggested_skill_draft"]).upper() == "JSON"
        with engine.connect() as connection:
            models_json = connection.scalar(
                text("SELECT available_models::text FROM llm_providers WHERE id = 1")
            )
            draft_json = connection.scalar(
                text("SELECT suggested_skill_draft::text FROM runs WHERE id = 1")
            )
        assert json.loads(models_json) == ["model-a"]
        assert json.loads(draft_json) == {"name": "draft"}

        saver, connection = _get_checkpointer(test_url)
        try:
            config = {"configurable": {"thread_id": "postgres-persistent-chat"}}
            _checkpoint_graph(saver).invoke({"value": "saved"}, config=config)
            state = _checkpoint_graph(saver).get_state(config)
        finally:
            connection.close()

        assert state.values == {"value": "saved"}
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
