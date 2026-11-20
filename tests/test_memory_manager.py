import json
from types import SimpleNamespace
from unittest.mock import patch

from hobees.config import settings
from hobees.core.memory_manager import extract_run_memories
from hobees.core.queen import Queen


class MockMemoryModel:
    def __init__(self, content):
        self.content = content
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = prompt
        return SimpleNamespace(content=self.content)


def test_auto_memory_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "enable_auto_memory", False)
    with patch("hobees.core.llm_factory.get_chat_model") as get_model:
        saved = extract_run_memories(
            goal="Test goal",
            output="Task completed",
            provider=SimpleNamespace(),
            model_name="test-model",
            hive_name="research",
            source_thread_id="test-thread",
            allow_hive_facts=True,
        )

    assert saved == 0
    get_model.assert_not_called()


def test_auto_memory_saves_scoped_facts_and_rejects_secrets(monkeypatch):
    monkeypatch.setattr(settings, "enable_auto_memory", True)
    model = MockMemoryModel(
        json.dumps(
            [
                {
                    "key": "user_prefers_python",
                    "content": "The user prefers Python examples.",
                    "scope": "global",
                },
                {
                    "key": "project_uses_postgres",
                    "content": "The project uses PostgreSQL.",
                    "scope": "hive",
                },
                {
                    "key": "api_key",
                    "content": "API_KEY=sk-test-secretvalue123456",
                    "scope": "global",
                },
            ]
        )
    )
    saved_memories = []
    with (
        patch("hobees.core.llm_factory.get_chat_model", return_value=model),
        patch(
            "hobees.core.memory_manager.upsert_memory",
            side_effect=lambda *args: saved_memories.append(args),
        ),
    ):
        saved = extract_run_memories(
            goal="Build the service",
            output="The service uses PostgreSQL.",
            provider=SimpleNamespace(),
            model_name="test-model",
            hive_name="service",
            source_thread_id="test-thread",
            allow_hive_facts=True,
        )

    assert saved == 2
    assert [memory[0] for memory in saved_memories] == [
        "global",
        "hive:service",
    ]
    assert all(memory[3] == "test-thread" for memory in saved_memories)


def test_ephemeral_hive_auto_memory_only_keeps_global_facts(monkeypatch):
    monkeypatch.setattr(settings, "enable_auto_memory", True)
    model = MockMemoryModel(
        json.dumps(
            [
                {"key": "preference", "content": "Concise answers.", "scope": "global"},
                {"key": "project_fact", "content": "Uses FastAPI.", "scope": "hive"},
            ]
        )
    )
    saved_memories = []
    with (
        patch("hobees.core.llm_factory.get_chat_model", return_value=model),
        patch(
            "hobees.core.memory_manager.upsert_memory",
            side_effect=lambda *args: saved_memories.append(args),
        ),
    ):
        saved = extract_run_memories(
            goal="Analyze this project",
            output="The project uses FastAPI.",
            provider=SimpleNamespace(),
            model_name="test-model",
            hive_name="dynamic-1234",
            source_thread_id="test-thread",
            allow_hive_facts=False,
        )

    assert saved == 1
    assert saved_memories[0][0] == "global"
    assert 'Only use scope "global"' in model.prompt


def test_queen_receives_global_memory(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "hobees.core.queen.get_chat_model",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "hobees.core.queen.build_memory_block",
        lambda namespaces: "Global memory marker" if namespaces == ["global"] else "",
    )
    monkeypatch.setattr(
        "hobees.core.queen.create_agent",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    Queen(
        provider=SimpleNamespace(),
        model_name="test-model",
        db_url="sqlite:///:memory:",
    )

    assert "Global memory marker" in captured["system_prompt"]
