"""Unit tests for Tool Registry and Tool Output Truncation."""

from hobees.core.context_manager import MAX_TOOL_OUTPUT_CHARS
from hobees.core.tool_registry import (
    TOOL_REGISTRY,
    get_tools,
    run_python_calc,
    set_thread_context,
)


def test_offloaded_output_can_be_read_back_with_the_path_the_model_was_shown(tmp_path):
    long_output = "Z" * (MAX_TOOL_OUTPUT_CHARS + 300)
    (tmp_path / "seed.txt").write_text(long_output, encoding="utf-8")
    thread_key = "shaapc:hive:dev-team:91318583"

    set_thread_context(thread_key, call_id="call_7", project_root=str(tmp_path))
    preview = TOOL_REGISTRY["read_file"].invoke({"path": "seed.txt"})
    assert "[... OUTPUT TRUNCATED" in preview

    shown = preview.split("Full output saved to: ", 1)[1].split("\n", 1)[0]
    assert ":" not in shown

    again = TOOL_REGISTRY["read_file"].invoke({"path": shown})
    assert not again.startswith("ERROR:")
    assert again.startswith("ZZZ")
    saved = tmp_path / "scratchpad" / "shaapc__hive__dev-team__91318583" / "call_7.txt"
    assert saved.read_text(encoding="utf-8") == long_output


def test_namespaced_thread_path_is_reported_as_an_error_not_raised(tmp_path):
    set_thread_context("t", project_root=str(tmp_path))
    result = TOOL_REGISTRY["read_file"].invoke(
        {"path": "scratchpad/worker:hive:dev-team/c1.txt"}
    )
    assert result.startswith("ERROR:")


def test_tool_registry_registration():
    assert "read_file" in TOOL_REGISTRY
    assert "write_file" in TOOL_REGISTRY
    assert "list_directory" in TOOL_REGISTRY
    assert "run_python_calc" in TOOL_REGISTRY


def test_get_tools():
    tools = get_tools(["read_file", "run_python_calc", "nonexistent_tool"])
    tool_names = [t.name for t in tools]
    assert "read_file" in tool_names
    assert "run_python_calc" in tool_names
    assert len(tools) == 2


def test_run_python_calc():
    set_thread_context("test_thread")
    res = run_python_calc.invoke({"expression": "2 + 3 * 4"})
    assert "14" in str(res)


def test_write_file_rejects_paths_outside_output_directory(tmp_path):
    set_thread_context("sandbox-test", project_root=str(tmp_path))

    result = TOOL_REGISTRY["write_file"].invoke(
        {"path": "../outside.txt", "content": "not written"}
    )

    assert result.startswith("ERROR:")
    assert not (tmp_path / "outside.txt").exists()

    result = TOOL_REGISTRY["write_file"].invoke(
        {"path": "../../outside.txt", "content": "not written"}
    )

    assert result.startswith("ERROR:")
    assert not (tmp_path.parent / "outside.txt").exists()


def test_write_file_uses_output_subdirectory(tmp_path):
    set_thread_context("output-test", project_root=str(tmp_path))

    result = TOOL_REGISTRY["write_file"].invoke(
        {"path": "output/result.txt", "content": "saved"}
    )

    assert result.startswith("WROTE ")
    assert (tmp_path / "output" / "result.txt").read_text() == "saved"
    assert not (tmp_path / "result.txt").exists()
    assert TOOL_REGISTRY["read_file"].invoke(
        {"path": "output/result.txt"}
    ) == "saved"
