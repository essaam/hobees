import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from hobees.cli.hive_cmd import (
    app as hive_cli_app,
    remove_hives,
    resolve_hive_selection,
)
from hobees.db import session as db_session
from hobees.db.models import Base, Bee, Hive, HiveMembership, LLMProvider, Run
from hobees.db.session import session_scope


def _use_test_database(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(
        db_session,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )
    return engine


def _create_hive(name="test-hive"):
    with session_scope() as session:
        provider = LLMProvider(
            alias="test-provider",
            provider_type="openai",
            api_key_env="NONE",
            default_model="test-model",
        )
        session.add(provider)
        session.flush()
        bee = Bee(
            name="test-bee",
            role_description="Test worker",
            system_prompt="Test prompt",
            provider_id=provider.id,
            model_name="test-model",
        )
        hive = Hive(
            name=name,
            supervisor_provider_id=provider.id,
            supervisor_model_name="test-model",
        )
        session.add_all((bee, hive))
        session.flush()
        session.add(HiveMembership(hive_id=hive.id, bee_id=bee.id))
        session.add(
            Run(
                thread_id="test-thread",
                hive_id=hive.id,
                mode="targeted",
                goal="Test goal",
            )
        )


def test_numbered_selection_supports_multiple_indices():
    assert resolve_hive_selection("1, 3 3", ["alpha", "beta", "gamma"]) == [
        "alpha",
        "gamma",
    ]


def test_remove_hives_preserves_bees_and_run_history(monkeypatch, tmp_path, request):
    engine = _use_test_database(monkeypatch, tmp_path)
    request.addfinalizer(engine.dispose)
    _create_hive()

    assert remove_hives(["test-hive"]) == ["test-hive"]

    with session_scope() as session:
        assert session.query(Hive).count() == 0
        assert session.query(HiveMembership).count() == 0
        assert session.query(Bee).filter_by(name="test-bee").count() == 1
        run = session.query(Run).filter_by(thread_id="test-thread").one()
        assert run.hive_id is None


def test_remove_hives_validates_all_names_before_deleting(
    monkeypatch, tmp_path, request
):
    engine = _use_test_database(monkeypatch, tmp_path)
    request.addfinalizer(engine.dispose)
    _create_hive()

    with pytest.raises(ValueError, match="missing-hive"):
        remove_hives(["test-hive", "missing-hive"])

    with session_scope() as session:
        assert session.query(Hive).filter_by(name="test-hive").count() == 1


def test_headless_cli_removes_named_hive(monkeypatch, tmp_path, request):
    engine = _use_test_database(monkeypatch, tmp_path)
    request.addfinalizer(engine.dispose)
    _create_hive()

    result = CliRunner().invoke(
        hive_cli_app, ["remove", "test-hive", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert "Hive 'test-hive' removed." in result.output
    with session_scope() as session:
        assert session.query(Hive).count() == 0
