"""Unit tests for the shared filesystem-safe path helper."""

from hobees.core.paths import safe_path_component
from hobees.core.tracing import trace_filename


def test_safe_path_component_replaces_windows_reserved_characters():
    assert safe_path_component("worker-1:hive:dev-team:91318583") == (
        "worker-1__hive__dev-team__91318583"
    )
    assert safe_path_component("bee|name?x*") == "bee__name__x__"
    assert safe_path_component("already-safe") == "already-safe"
    assert safe_path_component("...") == "unknown"
    assert safe_path_component("a:b", separator="_") == "a_b"


def test_trace_filename_uses_the_same_safe_component():
    key = "worker-1:hive:dev-team:91318583"
    assert trace_filename(key) == f"{safe_path_component(key)}.jsonl"
    assert ":" not in trace_filename(key)
    assert ":" not in safe_path_component(key)
