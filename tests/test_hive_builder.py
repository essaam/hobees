"""Unit tests for Hive Builder and dynamic graph compilation."""

from __future__ import annotations

import asyncio
import json
import pytest
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from langgraph.checkpoint.memory import MemorySaver

from hobees.core.hive_builder import hive_app, hive_app_async
from hobees.db.backends import get_postgres_checkpoint_url, render_db_url
from hobees.db.models import Hive, Bee, LLMProvider


class MockChatModel(BaseChatModel):
    responses: list = []
    recorded_inputs: list[list] = []
    idx: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.recorded_inputs.append(messages)
        res = self.responses[self.idx] if self.responses else "Mock reply"
        if self.responses and self.idx < len(self.responses) - 1:
            self.idx += 1
        if isinstance(res, str):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=res))])
        return ChatResult(generations=[ChatGeneration(message=res)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "mock"


def test_hive_app_compilation_and_execution(tmp_path):
    prov = LLMProvider(
        id=1,
        alias="test-prov",
        provider_type="openai",
        default_model="test-model",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        context_window_tokens=128000,
    )

    bee1 = Bee(
        id=1,
        name="worker1",
        role_description="Test worker bee",
        system_prompt="You are a test worker.",
        provider_id=1,
        model_name="test-model",
        tool_names=["run_python_calc"],
        thinking_level="off",
    )
    bee1.skills = []

    bee2 = Bee(
        id=2,
        name="worker2",
        role_description="Another test worker",
        system_prompt="You are another test worker.",
        provider_id=1,
        model_name="test-model",
        tool_names=[],
        thinking_level="off",
    )
    bee2.skills = []

    hive = Hive(
        id=1,
        name="test-hive",
        goal_description="Test hive goal",
        supervisor_provider_id=1,
        supervisor_model_name="test-model",
        supervisor_prompt="You are supervisor for {hive_name}. Workers:\n{worker_roster}",
        is_dynamic=False,
        project_path=str(tmp_path),
    )

    mock_sup_model = MockChatModel()
    mock_sup_model.responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "transfer_to_worker1", "args": {"description": "Perform task"}, "id": "call_1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "transfer_to_worker2", "args": {"description": "Perform another task"}, "id": "call_2"}],
        ),
        "Final supervisor synthesis: Task complete.",
    ]
    mock_worker_model = MockChatModel()
    mock_worker_model.responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_python_calc",
                    "args": {"expression": "2+2"},
                    "id": "calc_1",
                }
            ],
        ),
        "Worker finished successfully.",
    ]
    mock_worker_model2 = MockChatModel()
    mock_worker_model2.responses = ["Another worker finished successfully."]
    worker_models = {"worker1": mock_worker_model, "worker2": mock_worker_model2}

    def fake_get_chat_model(provider, model_name, temperature, callbacks=None, thinking_level=None):
        bee_name = str(callbacks[0].bee_name) if callbacks else ""
        if bee_name.endswith("_supervisor"):
            return mock_sup_model
        return worker_models[bee_name]

    with (
        patch("hobees.core.hive_builder.get_chat_model", side_effect=fake_get_chat_model),
        patch(
            "hobees.core.hive_builder.build_memory_block",
            return_value="Scoped supervisor memory marker",
        ) as build_memory,
    ):
        with hive_app(
            hive=hive,
            bees=[bee1, bee2],
            providers={1: prov},
            db_url="sqlite:///:memory:",
            thread_id="test_thread_123",
        ) as app:
            assert app is not None
            res = app.invoke(
                {"messages": [HumanMessage(content="Start the job")]},
                config={"configurable": {"thread_id": "test_thread_123"}},
            )
            assert "messages" in res
            final_msg = res["messages"][-1]
            assert "Task complete" in str(final_msg.content)
    worker1_messages = mock_worker_model.recorded_inputs[0]
    assert len(worker1_messages) == 1
    assert isinstance(worker1_messages[0], SystemMessage)
    assert "You are a test worker." in worker1_messages[0].content
    assert "Perform task" in worker1_messages[0].content
    supervisor_messages = mock_sup_model.recorded_inputs[0]
    supervisor_system = next(
        message for message in supervisor_messages if isinstance(message, SystemMessage)
    )
    assert "Scoped supervisor memory marker" in supervisor_system.content
    build_memory.assert_called_once_with(["global", "hive:test-hive"])
    worker2_messages = mock_worker_model2.recorded_inputs[0]
    assert len(worker2_messages) == 1
    assert isinstance(worker2_messages[0], SystemMessage)
    assert "You are another test worker." in worker2_messages[0].content
    assert "Perform another task" in worker2_messages[0].content
    trace_records = [
        json.loads(line)
        for line in (tmp_path / "traces" / "test_thread_123.jsonl").read_text().splitlines()
    ]
    trace_events = [record["event_type"] for record in trace_records]
    assert trace_events[0] == "HIVE_START"
    assert trace_events[-1] == "HIVE_COMPLETE"
    assert "WORKER_START" in trace_events
    assert "WORKER_END" in trace_events
    assert "TOOL_START" in trace_events
    assert "TOOL_END" in trace_events
    tool_start = next(
        record for record in trace_records if record["event_type"] == "TOOL_START"
    )
    assert tool_start["source"] == "worker1"
    assert tool_start["target"] == "run_python_calc"
    assert tool_start["payload"]["argument_names"] == ["expression"]
    assert "2+2" not in json.dumps(tool_start)
    assert all("2+2" not in json.dumps(record) for record in trace_records)


def test_file_sqlite_checkpoint_resumes_across_hive_apps(tmp_path):
    prov = LLMProvider(
        id=1,
        alias="test-prov",
        provider_type="openai",
        default_model="test-model",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        context_window_tokens=128000,
    )
    bee = Bee(
        id=1,
        name="worker",
        role_description="Test worker",
        system_prompt="You are a test worker.",
        provider_id=1,
        model_name="test-model",
        tool_names=[],
        thinking_level="off",
    )
    bee.skills = []
    hive = Hive(
        id=1,
        name="checkpoint-hive",
        goal_description="Test resume",
        supervisor_provider_id=1,
        supervisor_model_name="test-model",
        supervisor_prompt="Supervisor {hive_name}: {worker_roster}",
        is_dynamic=False,
        project_path=str(tmp_path / "workspace"),
    )
    db_path = tmp_path / "checkpoints.sqlite"
    db_url = f"sqlite:///{db_path}"

    with patch(
        "hobees.core.hive_builder.get_chat_model",
        return_value=MockChatModel(),
    ):
        for goal in ("First task", "Second task"):
            async def invoke_goal():
                async with hive_app_async(
                    hive=hive,
                    bees=[bee],
                    providers={1: prov},
                    db_url=db_url,
                    thread_id="resumable-thread",
                ) as app:
                    return await app.ainvoke(
                        {"messages": [HumanMessage(content=goal)]},
                        config={"configurable": {"thread_id": "resumable-thread"}},
                    )

            result = asyncio.run(invoke_goal())

    user_messages = [
        message.content
        for message in result["messages"]
        if isinstance(message, HumanMessage)
    ]
    assert user_messages == ["First task", "Second task"]


def _postgres_run_inputs(tmp_path):
    prov = LLMProvider(
        id=1,
        alias="test-prov",
        provider_type="openai",
        default_model="test-model",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        context_window_tokens=128000,
    )
    bee = Bee(
        id=1,
        name="worker",
        role_description="Test worker",
        system_prompt="You are a test worker.",
        provider_id=1,
        model_name="test-model",
        tool_names=[],
        thinking_level="off",
    )
    bee.skills = []
    hive = Hive(
        id=1,
        name="pg-hive",
        goal_description="Test",
        supervisor_provider_id=1,
        supervisor_model_name="test-model",
        supervisor_prompt="Supervisor {hive_name}: {worker_roster}",
        is_dynamic=False,
        project_path=str(tmp_path / "workspace"),
    )
    return hive, [bee], {1: prov}


def test_the_sync_postgres_saver_gets_the_real_password(tmp_path):
    """SQLAlchemy and `hobees init` connect with the URL object, so they keep the password.
    A run that stringifies it first sends `***`, and Postgres answers with a failure that
    looks like a wrong password rather than a lost one."""
    from sqlalchemy.engine import make_url

    hive, bees, providers = _postgres_run_inputs(tmp_path)
    url = make_url("postgresql+psycopg://hobees:secretpass@localhost:5432/hobeesdb")
    captured: list[str] = []

    def fake_from_conn_string(conn_string):
        captured.append(conn_string)

        @contextmanager
        def saver_context():
            yield MemorySaver()

        return saver_context()

    with (
        patch("hobees.core.hive_builder.get_chat_model", return_value=MockChatModel()),
        patch("langgraph.checkpoint.postgres.PostgresSaver.from_conn_string", fake_from_conn_string),
    ):
        with hive_app(hive=hive, bees=bees, providers=providers, db_url=url, thread_id="pg-thread"):
            pass

    assert captured == ["postgresql://hobees:secretpass@localhost:5432/hobeesdb"]
    assert "***" not in captured[0]
    # The same URL through str() is what used to reach the saver.
    assert str(url) == "postgresql+psycopg://hobees:***@localhost:5432/hobeesdb"


def test_the_async_postgres_saver_gets_the_real_password(tmp_path):
    from sqlalchemy.engine import make_url

    hive, bees, providers = _postgres_run_inputs(tmp_path)
    url = make_url("postgresql+psycopg://hobees:secretpass@localhost:5432/hobeesdb")
    captured: list[str] = []

    def fake_from_conn_string(conn_string):
        captured.append(conn_string)

        @asynccontextmanager
        async def saver_context():
            # The saver must be a real BaseCheckpointSaver for graph.compile(), so the
            # in-memory one stands in while the connection string is captured.
            saver = MemorySaver()
            saver.setup = AsyncMock()
            yield saver

        return saver_context()

    async def run():
        with (
            patch("hobees.core.hive_builder.get_chat_model", return_value=MockChatModel()),
            patch("langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string", fake_from_conn_string),
        ):
            async with hive_app_async(hive=hive, bees=bees, providers=providers, db_url=url, thread_id="pg-thread"):
                return None

        return None

    asyncio.run(run())
    assert captured == ["postgresql://hobees:secretpass@localhost:5432/hobeesdb"]
    assert "***" not in captured[0]


def test_a_stringified_url_is_refused_before_it_can_fail_authentication(tmp_path):
    from sqlalchemy.engine import make_url

    url = make_url("postgresql+psycopg://hobees:secretpass@localhost:5432/hobeesdb")

    # A string that already lost the password cannot be recovered, so the run reports where
    # it was lost instead of connecting with `***`.
    with pytest.raises(ValueError, match="masked password"):
        get_postgres_checkpoint_url(str(url))

    assert render_db_url(url) == "postgresql+psycopg://hobees:secretpass@localhost:5432/hobeesdb"
    assert "secretpass" in get_postgres_checkpoint_url(url)
    assert "secretpass" in get_postgres_checkpoint_url(render_db_url(url))
    # A plain string URL (what settings.database_url holds) keeps its password too.
    assert "secretpass" in get_postgres_checkpoint_url(
        "postgresql+psycopg://hobees:secretpass@localhost:5432/hobeesdb"
    )
