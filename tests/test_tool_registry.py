"""Unit tests for Tool Registry and Tool Output Truncation."""

from hobees.core.tool_registry import (
    TOOL_REGISTRY,
    get_tools,
    run_python_calc,
    set_thread_context,
)


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
