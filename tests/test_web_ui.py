"""Regression tests for the bundled Web UI SPA source.

The SPA is built from `web-ui/` into `src/hobees/web/static/`. These checks keep
the user-visible behaviours in place:

* the Workbench provider/model/target pickers survive navigation between views,
* the assistant chat sends the selected model,
* the Command Palette handles arrow keys from any focus position and no longer
  advertises that legend in its footer.
"""

from __future__ import annotations

from pathlib import Path

WEB_UI_SRC = Path(__file__).resolve().parents[1] / "web-ui" / "src"


def read(relative: str) -> str:
    path = WEB_UI_SRC / relative
    assert path.is_file(), f"Missing web-ui source file: {relative}"
    return path.read_text(encoding="utf-8")


def test_storage_helpers_guard_against_unavailable_local_storage():
    storage = read("utils/storage.ts")
    assert "localStorage" in storage
    assert "typeof window" in storage
    assert "hobees.web-ui" in storage


def test_workbench_picker_state_is_kept_in_the_app_context():
    context = read("context/AppContext.tsx")
    assert "WorkbenchSelections" in context
    assert "workbenchSelections" in context
    assert "readStored" in context and "writeStored" in context

    workbench = read("pages/Workbench.tsx")
    # Selection comes from the context (persisted), not from component-local
    # state that is lost when the view is remounted.
    assert "workbenchSelections[scope]" in workbench
    assert "setWorkbenchSelection" in workbench
    assert "setEntityName" not in workbench
    # Stale selections only fall back to the first entry when missing/removed.
    assert "includes(entityName)" in workbench


def test_command_palette_handles_arrow_keys_from_any_focus():
    palette = read("components/CommandPalette.tsx")
    # Window-level handler (focus anywhere) plus the palette's own keydown, with
    # a guard so a single key press is not processed by both paths.
    assert "window.addEventListener('keydown'" in palette
    assert "onKeyDown={(e) => handleKey(e.nativeEvent)}" in palette
    assert "defaultPrevented" in palette
    assert "ArrowDown" in palette
    assert "ArrowUp" in palette
    assert "scrollIntoView" in palette
    # The footer must not advertise arrow-key navigation the user cannot rely on.
    assert "↑↓" not in palette


def test_assistant_chat_picks_a_model_from_auto_detection():
    workbench = read("pages/Workbench.tsx")
    assert 'aria-label="Select model"' in workbench
    assert "modelOptions" in workbench
    assert "assistantModel" in workbench

    studio = read("pages/Studio.tsx")
    assert "Detect models" in studio
    assert "Test model" in studio

    types = read("types/index.ts")
    assert "ProviderModelsResponse" in types
    assert "ProviderModelTestResponse" in types
    run_create = types.split("export interface RunCreate")[1]
    assert "model?" in run_create


def test_command_palette_list_is_exposed_as_a_listbox():
    palette = read("components/CommandPalette.tsx")
    assert 'role="listbox"' in palette
    assert 'role="option"' in palette
    assert "aria-activedescendant" in palette
    # The footer shows filtering/Enter only — no arrow-key navigation claim.
    assert "Type to filter · Enter to run" in palette


def test_model_selection_endpoints_are_wired_in_the_api_client():
    client = read("api/client.ts")
    assert "/providers/models" in client
    assert "/providers/test" in client

    hooks = read("hooks/useApi.ts")
    assert "useDetectProviderModels" in hooks
    assert "useTestProviderModel" in hooks


def test_assistant_run_sends_the_selected_model():
    workbench = read("pages/Workbench.tsx")
    assert "model: scope === 'assistant' ? assistantModel" in workbench
    assert "workbenchModels" in workbench
    assert "Boolean(assistantModel)" in workbench

