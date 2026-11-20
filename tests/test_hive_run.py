"""Unit tests for headless CLI hive run command."""

import asyncio
import json
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hobees.cli.hive_cmd import cmd_hive_run
from hobees.db import session as db_session
from hobees.db.models import Base, Hive, Bee, LLMProvider, HiveMembership
from hobees.db.session import session_scope


def test_cmd_hive_run_execution(tmp_path, capsys, monkeypatch, request):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    request.addfinalizer(engine.dispose)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(
        db_session,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )
    skill_draft = {
        "name": "headless-run-skill",
        "description": "A generated headless run skill",
        "instructions": "Perform the workflow.",
        "tags": [],
        "bee_names": [],
    }
    monkeypatch.setattr(
        "hobees.core.skill_harvester.harvest_completed_run",
        lambda _run_id: skill_draft,
    )

    import uuid
    suffix = uuid.uuid4().hex[:6]
    prov_alias = f"run-prov-{suffix}"
    bee_name = f"run-bee-{suffix}"
    hive_name = f"run-team-{suffix}"

    # Setup database with a provider, bee, and hive
    with session_scope() as session:
        prov = LLMProvider(
            alias=prov_alias,
            provider_type="openai",
            api_key_env="OPENAI_API_KEY",
            default_model="gpt-test",
            input_cost_per_1m=0.0,
            output_cost_per_1m=0.0,
        )
        session.add(prov)
        session.flush()

        bee = Bee(
            name=bee_name,
            role_description="Executes run tests",
            system_prompt="You are a run bee.",
            provider_id=prov.id,
            model_name="gpt-test",
            tool_names=[],
        )
        session.add(bee)
        session.flush()

        hive = Hive(
            name=hive_name,
            goal_description="Automated run hive",
            supervisor_provider_id=prov.id,
            supervisor_model_name="gpt-test",
            is_dynamic=False,
        )
        session.add(hive)
        session.flush()

        session.add(HiveMembership(hive_id=hive.id, bee_id=bee.id))

    # Mock hive_app so no live LLM call is made
    class MockApp:
        async def ainvoke(self, inputs, config=None):
            from hobees.core.tracing import EventBroker

            EventBroker.get_instance().publish(
                {
                    "thread_id": config["configurable"]["thread_id"],
                    "event_type": "TOOL_START",
                    "source": "coder",
                    "target": "write_file",
                }
            )
            await asyncio.sleep(0)
            return {"messages": [AIMessage(content="Goal accomplished by run-team")]}

    class MockContextManager:
        async def __aenter__(self):
            return MockApp()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch(
        "hobees.core.hive_builder.hive_app_async",
        return_value=MockContextManager(),
    ) as hive_app_mock:
        cmd_hive_run(
            hive_name=hive_name,
            goal="Test headless run",
            thread_id=f"th_{suffix}",
            artifacts_dir=str(tmp_path),
            quiet=True,
        )
        cmd_hive_run(
            hive_name=hive_name,
            goal="Resume headless run",
            thread_id=f"th_{suffix}",
            artifacts_dir=str(tmp_path),
            quiet=False,
        )

    assert hive_app_mock.call_args.kwargs["artifact_root"] == tmp_path
    captured_output = capsys.readouterr().out
    assert "Goal accomplished by run-team" in captured_output
    assert "[TOOL_START] coder -> write_file" in captured_output
    manifest_path = tmp_path / "run_manifest.json"
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert data["hive_name"] == hive_name
    assert data["last_run"]["status"] == "completed"
    assert data["last_run"]["goal"] == "Resume headless run"
    assert data["last_run"]["run_id"] == hive_app_mock.call_args.args[5]
    assert data["last_run"]["suggested_skill_draft"] == skill_draft
    assert len(data["runs"]) == 2
