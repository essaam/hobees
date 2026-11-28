"""Regression tests for the bundled Web UI SPA source.

The SPA is built from `web-ui/` into `src/hobees/web/static/`. These checks keep
the user-visible behaviours in place:

* the Workbench provider/model/target pickers survive navigation between views,
* the assistant chat sends the selected model,
* the last Workbench run (thread, activity feed, reply, prompt) survives a view
  change and can be cleared with a New session button,
* the Workbench output box scrolls,
* the Command Palette handles arrow keys from any focus position and no longer
  advertises that legend in its footer,
* the Studio view is labelled Studio and its reset panel asks for a typed Y(es)
  before removing the slate.
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


def test_studio_has_a_containers_tab_wired_to_the_api():
    studio = read("pages/Studio.tsx")
    assert "type StudioTab = 'setup' | 'hives' | 'bees' | 'providers' | 'skills' | 'containers'" in studio
    assert "ContainersTab" in studio
    assert "useContainerPlan" in studio
    assert "useSaveContainerFiles" in studio
    # Generation only: the tab writes files, it never starts or stops a container.
    assert "Update spec" in studio
    assert "Download all files" in studio
    assert "setEnvSample(res.env_sample)" in studio
    # The model on screen is the model that is saved: one resolution order in the form,
    # the picker and the API, so saving cannot be blocked while a model looks chosen.
    assert "function pickModel(" in studio
    # The models the picker fetches have to be visible to the form, not only inside the
    # picker - otherwise the guard can still see an empty value.
    assert "detectedCache" in studio
    assert "detectedCache[key] = res.models" in studio
    assert "value={model} onChange={setModelName}" in studio
    assert "reports no model - detect models or type one" in studio
    assert "runAction" not in studio
    assert "/containers/action" not in read("api/client.ts")
    assert "Save to project" in studio
    assert "Export compose" in studio
    assert "docker is not available on this host" in studio
    assert "nothing here starts or stops a container" in studio

    client = read("api/client.ts")
    for endpoint in ("/containers/plan", "/containers/files"):
        assert endpoint in client

    hooks = read("hooks/useApi.ts")
    for hook in ("useContainerPlan", "useBuildContainerPlan", "useSaveContainerFiles"):
        assert hook in hooks

    types = read("types/index.ts")
    assert "ContainerPlanResponse" in types
    assert "ContainerSpec" in types


    palette = read("components/CommandPalette.tsx")
    assert "tab=containers" in palette
    assert "Container preparation" in palette


def test_workbench_surfaces_gates_open_on_its_own_run():
    workbench = read("pages/Workbench.tsx")
    assert "pendingApprovals" in workbench
    assert "sessionApprovals" in workbench
    assert "a.thread_id === activeThreadId" in workbench
    assert "Gate open on this run" in workbench
    assert "ApprovalActionCard" in workbench
    assert "Awaiting approval" in workbench


def test_workbench_session_state_is_kept_in_the_app_context():
    context = read("context/AppContext.tsx")
    assert "WorkbenchSession" in context
    assert "workbenchSessions" in context
    assert "newWorkbenchSession" in context
    assert "MAX_SESSION_EVENTS" in context

    workbench = read("pages/Workbench.tsx")
    assert "workbenchSessions[scope]" in workbench
    assert "setSession" in workbench
    # The view is restored, not restarted: a run that was still going is rejoined.
    assert "if (!isRunning || !activeThreadId) return;" in workbench
    assert "/stream" in workbench
    # And the user can clear it deliberately.
    assert "startNewSession" in workbench
    assert "New session" in workbench
    assert "setEvents" not in workbench
    assert "setFinalOutput" not in workbench


def test_workbench_output_and_activity_panels_scroll():
    workbench = read("pages/Workbench.tsx")
    output_box = workbench.split("{/* Output Body")[1]
    assert "overflow-y-auto" in output_box
    assert "max-h-" in output_box
    # The activity feed keeps its own scroll area.
    assert "max-h-56 overflow-y-auto" in workbench


def test_the_studio_view_is_labelled_studio():
    layout = read("components/Layout.tsx")
    studio = read("pages/Studio.tsx")
    workbench = read("pages/Workbench.tsx")
    assert "{ to: '/studio', label: 'Studio'" in layout
    assert ">Studio</h1>" in studio
    # Nothing in the UI should still call it "Hive Studio".
    for source in (layout, studio, workbench):
        assert "Hive Studio" not in source


def test_model_picker_is_shared_by_provider_bee_and_hive_dialogs():
    studio = read("pages/Studio.tsx")
    assert "function ModelPicker" in studio
    assert "Detect models" in studio
    assert "Test model" in studio
    for dialog in ("ProviderDialog", "BeeDialog", "HiveDialog"):
        body = studio.split(f"function {dialog}(")[1]
        assert "ModelPicker" in body, f"{dialog} must use the auto-detected model picker"


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


def test_studio_reset_panel_confirms_before_cleaning_the_slate():
    studio = read("pages/Studio.tsx")

    # The panel shows the plan, the --all scope is opt-in, and the action is gated
    # on a typed Y(es) so a stray click cannot clear the slate.
    assert "ResetPanel" in studio
    assert "<ResetPanel readOnly={readOnly} />" in studio
    assert "useResetPlan({ include_artifacts: includeArtifacts })" in studio
    assert "['y', 'yes'].includes(answer.trim().toLowerCase())" in studio
    assert "Type Y (yes) to confirm" in studio
    assert "disabled={!confirmed || resetSlate.isPending}" in studio
    assert "Read-only mode: reset is disabled" in studio

    client = read("api/client.ts")
    assert "getResetPlan" in client and "resetSlate" in client

    hooks = read("hooks/useApi.ts")
    assert "useResetPlan" in hooks and "useResetSlate" in hooks
    assert "queryKey: ['reset', 'plan'" in hooks

    types = read("types/index.ts")
    assert "ResetPlanResponse" in types and "ResetResponse" in types

def test_quick_setup_tab_carries_templates_and_only_reset():
    studio = read("pages/Studio.tsx")

    # Quick setup is its own tab; templates sit on top of it and Reset below.
    assert "type StudioTab = 'setup' | 'hives'" in studio
    assert "{ id: 'setup', label: 'Quick setup', count: templates.length, icon: Layers }" in studio
    # Landing tab: Quick setup only when the slate is still empty, otherwise Hives.
    assert "const STUDIO_TABS: StudioTab[] = ['setup', 'hives', 'bees', 'providers', 'skills', 'containers']" in studio
    assert "defaultTabResolved" in studio
    assert "if (providers.length + bees.length + hives.length > 0) setTab('hives');" in studio
    assert "{tab === 'setup' && <QuickSetupTab readOnly={readOnly} />}" in studio
    assert "<TemplatesPanel readOnly={readOnly} />" in studio
    assert "<ResetPanel readOnly={readOnly} />" in studio
    # Reset is rendered in exactly one place — inside Quick setup — and is labelled Reset.
    assert studio.count("<ResetPanel readOnly={readOnly} />") == 1
    assert ">Reset</h2>" in studio
    assert "function QuickSetupTab" in studio

    # A colliding blueprint is applied only after a typed Y (yes), in either mode,
    # and skip is the default so existing entries are kept as they are.
    assert "'skip' | 'overwrite'" in studio
    assert "collides:" in studio
    assert "if (needsConfirm && !confirmed) return;" in studio
    assert "{tab === 'providers' && <ProviderDetectionPanel readOnly={readOnly} />}" in studio

    palette = read("components/CommandPalette.tsx")
    assert "quick-setup" in palette

    client = read("api/client.ts")
    for name in ("getTemplates", "applyTemplate", "detectProviders", "registerDetectedProviders"):
        assert name in client

    hooks = read("hooks/useApi.ts")
    for name in ("useTemplates", "useApplyTemplate", "useDetectProviders", "useRegisterDetectedProviders"):
        assert name in hooks

    types = read("types/index.ts")
    for name in ("TemplateItem", "TemplateApplyRequest", "DetectedProvider", "ProviderDetectionResponse"):
        assert name in types
def test_dev_server_proxy_matches_the_web_ui_default_port():
    """The SPA dev server must proxy to the same port `hobees web` binds by default."""
    vite = Path(__file__).resolve().parents[1] / "web-ui" / "vite.config.ts"
    text = vite.read_text(encoding="utf-8")
    assert "http://127.0.0.1:6543" in text
def test_containers_tab_runs_the_goal_from_a_file_or_pipe():
    studio = read("pages/Studio.tsx")

    assert "Run for this goal" in studio
    assert "(['mount', 'bake', 'stdin'] as const)" in studio
    # The run command follows the fields: one --profile per profile value, the service key,
    # and -T when the goal is piped instead of read from a file.
    assert "docker compose" in studio
    assert "profiles.join(' ')" in studio
    assert "run${tty} --rm" in studio
    assert "fields.service" in studio
    assert "The goal text is never written into the entrypoint script" in studio
    assert "hobees init --config" in studio
    assert "Export hobees.yaml" in studio
    assert "Export entrypoint" in studio
    assert ".env.sample" in studio
    assert "setEnvSample(res.env_sample)" in studio
    assert "The exit code is how a pipeline learns the outcome" in studio
    assert "State.ExitCode" in studio
    assert "hobees pipeline status" in studio
    # Postgres data is a Docker volume, so it is declared in the top-level block at the bottom
    # of the file instead of being a host folder init-dirs creates.
    assert "const namedVolumes = () => {" in studio
    assert "docker compose down -v" in studio
    # The volumes field accepts both kinds, which is what decides whether a mount is prepared
    # by init-dirs or declared as a volume.
    assert "Volumes (host:container or volume:container, comma-separated)" in studio
    assert "Download all files" in studio

def test_preview_refreshes_the_run_command_with_the_settings():
    studio = read("pages/Studio.tsx")
    # The tab used to show a stale run command: preview must refresh the whole plan.
    for call in ("setPipeline(res.pipeline_command)", "setConfig(res.config)", "setEntrypoint(res.entrypoint)"):
        assert call in studio
    assert "include the web service" in studio
def test_the_bee_and_hive_forms_resolve_the_model_they_show():
    studio = read("pages/Studio.tsx")
    body = studio[studio.index("function pickModel("):studio.index("function ModelPicker({")]
    # Requested, then provider default, then assistant, then the first detected model.
    for step in ("requested.trim()", "provider?.default_model", "provider?.assistant_model", "provider?.available_models?.[0]"):
        assert step in body
    # The saved row uses that resolved value, and the error only fires when nothing is known.
    assert "model_name: model," in studio and "supervisor_model_name: model," in studio
    assert "if (!model) {" in studio
