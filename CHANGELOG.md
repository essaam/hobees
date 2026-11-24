# Changelog

Notable project changes are recorded here. The package version is defined in
`pyproject.toml`. Before a release, move the relevant entries from **Unreleased**
to a heading matching that version and add the release date.

## Unreleased

### New Features

- Web UI: the assistant chat now uses an explicitly selected model. The Workbench
  shows a model picker built from the provider's auto-detected models and the
  selection is remembered per provider.
- Web UI: the Provider, Bee and Hive dialogs in Studio share one model picker
  with a **Detect models** action (provider auto-detection) and an inline
  **Test model** check that runs a single minimal completion.
- Web API: `GET /api/v1/providers/models` (auto-detection, cached on the provider
  row when not read-only) and `POST /api/v1/providers/test` (config + one minimal
  completion, reasons reported inline); `POST /api/v1/runs` accepts `model` and
  rejects an assistant run with no model instead of guessing one.

### Fixed

- Core: path segments derived from namespaced thread keys now go through
  `hobees.core.paths.safe_path_component()` (`:` → `__`), so the scratchpad
  directory that stores offloaded tool output is a legal path on Windows. The
  preview a Bee is shown now names the directory it can actually read back, and
  tool path resolution returns `ERROR:` for a path that cannot exist on the
  platform instead of raising `OSError` (`[WinError 123]`) during a run.
- Web UI: Studio has a **Containers** tab that generates a custom `compose.yaml` and
  `Dockerfile` from the live settings and the registered providers, shows the validation
  warnings, saves the two files to the project root or exports them for download, and can
  spin the stack up/down with `Start`, `Status`, `Logs` and `Stop`. Environment values stay
  `${NAME}` references (never literal keys), the generated Dockerfile runs as a non-root
  user with `uv sync --no-dev`, and the web layer only ever runs the allowlisted
  `docker compose` subcommands (`up`, `down`, `ps`, `logs`) with fixed arguments; anything
  else is rejected, and actions are disabled in `--read-only` mode or when `docker` is not
  installed on the host. Endpoints: `GET/POST /api/v1/containers/plan`,
  `POST /api/v1/containers/files`, `POST /api/v1/containers/action`.
- Web UI: the Workbench now shows a gate that is open on the run it is watching
  (Approve / Edit / Reject inline, plus an `Awaiting approval` status), instead of
  only in the Approvals drawer.
- CLI: `hobees bee create` and `hobees bee update` accept `--approval`, so a gate can
  be declared without going through a config file. `hobees import` and the shared Bee
  handlers now warn when `require_approval` names a tool that is not in the tool
  registry — a gate on an unregistered tool can never fire (the README example used
  `run_shell`, which is not a built-in tool).
- Web UI: the last Workbench state is kept per scope in the app context (thread,
  activity feed, reply, prompt), so returning to the view shows the same run
  instead of restarting it; a run that was still going is rejoined on return, and
  a **New session** button clears the session and starts a fresh thread.
- Web UI: the Workbench output/response box now has its own vertical scrollbar
  (`max-h-[60vh] overflow-y-auto`) instead of growing the page, matching the live
  activity feed above it.
- Web UI: the Studio view is now labelled **Studio** (previously "Hive Studio") in
  the navigation, the page heading, the Workbench links to it and the API messages
  that point users there; `specs/webapp.md`, the FastAPI description and the
  `hobees web` help text match.
- Web UI: the Workbench provider/target picker no longer resets to the first
  entry when switching views or the Assistant/Hive/Bee tabs. Pickers now live in
  the app context per scope and are persisted (localStorage), so the chosen
  provider is restored on return; it only falls back to the first entry when the
  remembered selection is missing or was deleted.
- Web UI: Command Palette arrow keys (↑/↓) now navigate the results from any focus
  position inside the palette, the highlight is clamped to the filtered list, and
  the active entry is scrolled into view. The footer legend no longer advertises
  arrow navigation (it now reads `Type to filter · Enter to run`).
- Web UI: the Studio provider form no longer offers `gemini`, which the backend
  expects as `google_genai`; provider types are validated on create.

## 0.1.0a5 - 2026-11-22

### New Features

- Adds config templates for quick start.
- Adds auto LLM provider discovery, runs once automatically on the first launch, runnable on-demand.

## 0.1.0a4 - 2026-11-22

### Improved

- Updated README for better clarity.

## 0.1.0a3 - 2026-11-21

### Fixed

- In local use, if no SQLite DB URL is predefined a default DB will be created.
- DB table gets initialised automatically.

## 0.1.0a2 - 2026-11-21

### Fixed

- Support chat in Windows interactive terminal.
- Use async-compatible persistent checkpointers for assistant and bee chats,
  fixing failures when streaming with file-backed SQLite or PostgreSQL.

