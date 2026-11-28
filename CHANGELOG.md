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
- CLI: `hobees reset` cleans the hobees slate — the env file, the SQLite database
  files and the config folders hobees created inside `~/.hobees` — and
  `hobees reset --all` additionally removes the generated output (artifacts, skills
  library, scratchpad cache). It lists what exists, always asks for a `Y (yes)` answer
  before deleting, and is headless-only: the interactive shell and the TUI do not offer
  it. Environment variables exported in the shell are never changed, a project `.env`
  you created is left alone, and a database served outside `~/.hobees` loses only the
  URL stored in the env file. The Studio page carries the same two scopes under the new
  **Quick setup** tab: `GET /api/v1/reset/plan` previews, `POST /api/v1/reset` applies
  only when the panel recorded a `Y (yes)` confirmation, requests from another origin are
  rejected, and both are blocked in `--read-only` mode. Reset is labelled **Reset** and is
  shown only on that tab.
- Web UI: Studio's **Quick setup** tab puts the built-in templates on top, above Reset.
  Each card lists what the blueprint creates and every name it already finds in the
  database, and a colliding template is applied only after a typed `Y (yes)` confirmation,
  whichever mode is chosen. **Skip existing** is the default so current work is left
  untouched; **Overwrite existing** is available once confirmed. Endpoints:
  `GET /api/v1/templates`, `POST /api/v1/templates/apply`.
- Web UI: the **Providers** tab has a **Detect providers** action — scan env vars and the
  local ports on demand, see the candidates with their source, then register only the ones
  you tick. Detection itself writes nothing (`POST /api/v1/providers/detect`), and it and
  `POST /api/v1/providers/detect/register` are disabled in `--read-only` mode.
- Core/CLI: `hobees import` accepts `--on-conflict skip | overwrite` (default `overwrite`,
  what an import always did) and the summary plus the confirmation now name every
  collision before anything is written; the CLI and the web template panel share one
  conflict analysis (`analyze_config_conflicts()`). A skipped hive or skill keeps its bee
  roster and assignments too.
- Web UI: the Studio **Containers** tab generates the whole deployable set from the active
  configuration: `compose.yaml`, `Dockerfile`, `hobees.yaml`, `goal.txt` and
  `docker-entrypoint.sh`. The entrypoint initializes the schema with the copied config and then
  runs the goal. The goal reaches the container as a read-only mount (default), a baked `COPY`
  (opt-in) or stdin, and the prompt text is never written into the script, so it cannot be read
  as shell. Save/export covers all five files, the tab shows the pipeline command, and the plan
  response reports the generated contents plus which files already exist at the project root.  The `Dockerfile` now mirrors the repo one (`uv tool install hobees` from PyPI, no source tree in
  the image), paths are relative to the project root, the container name is read at run time instead
  of baking the host name in, running the web app inside the container is optional and commented out
  by default, and the shown pipeline command follows the settings in the panel.  The generated `Dockerfile` no longer bakes a `CMD`: the entrypoint script decides what runs, so the
  command line duplicated it (the reason is written as a comment in the generated file), and compose
  writes `command` only for an explicit override. The Containers tab is file-generation only - the
  start/stop/status/logs section is gone - a field change reaches the files only after clicking
  **Update spec**, and **Download all files** gives each file as its own download rather than a pack.
- CLI: `hobees pipeline status` reports how a run ended for a pipeline manager - the manifest entry or
  the run row, with status, error and the exit code to act on - and can wait for a terminal state with
  `--poll`/`--timeout`. Run manifests now carry `exit_code`, so the shell signal and the JSON cannot
  disagree. Codes: 0 completed, 1 failed, 2 stopped for an approval a headless run cannot answer,
  3 still running. The generated entrypoint keeps the path intact (`set -eu`, then `exec`), so nothing
  between hobees and the container's exit code can swallow it, and a remote daemon still reports the
  container's code to the caller.
- Containers: the generated set now includes ".env.sample" - the key names the generated files
  read, listed without values, required first (the provider keys and the Postgres password the
  database URL cannot default) and then the names compose falls back on. Save and Download all
  include it, and the plan reports which files already exist at the project root.
- Core: detection defaults now include **DeepSeek** (`DEEPSEEK_API_KEY`,
  `https://api.deepseek.com/v1`).
- CLI: `hobees run`, `hobees prompt` and `hobees hive run` accept `--goal-file <path>`
  and `-`/piped stdin, in that precedence order (argument > file > stdin). A long prompt is
  carried by a file or a pipe rather than shell quoting or an environment variable, which is
  what makes a container/CI step readable. With no goal supplied the command exits with the
  usable ways to give one; `prompt`'s `--goal-file` sits last in the signature so existing
  positional calls keep working.

### Changed

- Web UI: the Studio Containers tab no longer runs `docker`. `POST /api/v1/containers/action`, the
  `up|down|ps|logs` allowlist and `run_compose()` are gone: the tab writes the generated files, and the
  pipeline (or a person) executes them, so the code stays the signal.
- Containers: the generated set now follows the files that are known to run against Docker, field for
  field, and writes them on **Update spec**.
  `compose.yaml` starts with an `init-dirs` service (alpine, running as root) that creates the folders the
  bind mounts point at - `./output`, `./skills` - and chowns them to
  `HOBEES_UID:HOBEES_GID` before the goal runner and Postgres start; both `depends_on` it with
  `service_completed_successfully`. The goal runner keeps `init: true`, `extra_hosts` for
  `host.docker.internal` (so a `host.docker.internal` base_url resolves), `restart: "no"` and the profile,
  and Postgres keeps its data in the named Docker volume `postgres_data`, declared in the top-level
  `volumes:` block at the bottom of the file (there is no host folder for `init-dirs` to prepare, Postgres owns
  the volume, and the data survives `docker compose down` - `docker compose down -v` removes it). A volume
  typed as a host path is still prepared by `init-dirs`, and a named volume mounted without being declared is
  reported as a warning. Postgres reads `./.env` instead of an inline `environment:` block, with the
  healthcheck quoting `$${POSTGRES_USER}`/`$${POSTGRES_DB}` so the container shell expands them.
  The image creates the user with the ids `.env` maps the host onto (1000/1000, not 10001), installs hobees
  into `/opt/uv-tools` with `UV_TOOL_BIN_DIR=/usr/local/bin`, and copies `hobees.yaml` and
  `docker-entrypoint.sh` under the home directory; the script then keeps the same four numbered steps
  (init, args override, `set --`, the goal), so the **run_init** checkbox now actually decides whether the
  init step is written.
  `.env.sample` is laid out in the sections `.env` carries: Host UID/GID mapping, Postgres credentials,
  Provider API keys, Hobees runtime configuration - paths and the hive come from there instead of being
  repeated in the compose `environment:` block.
  The run command follows the profiles field rather than a hardcoded `pipeline`:
  `docker compose --profile <profile> run --rm <service>`, one `--profile` per value, with `-T` when the
  goal is piped, and the panel shows which folders `init-dirs` prepares.
- CLI: `hobees run` and `hobees hive run` exit **2** when the run stops for an approval instead of
  looking successful with 0.
- CLI: the Web UI default port is now **6543** (`hobees web` without `--port`, and the
  `web-ui` dev-server proxy target follows it). `hobees serve` stays on 8420, and port
  8080 is still the llama-server detection default — the two are unrelated.

### Fixed

- Database: `hobees run` no longer authenticates with a masked password. `str(url)` and
  `f"{url}"` write the password as `***`, and `hobees.core.hive_builder._build_hive_graph()` returned
  `str(db_url)` - so both the sync and the async checkpointer got `postgresql://hobees:***@host/db`
  from `get_postgres_checkpoint_url()`, while SQLAlchemy and `hobees init` kept connecting because
  they hold the URL object itself. The hive paths now render with `render_db_url()`
  (`render_as_string(hide_password=False)`), which accepts `str | URL` and keeps `engine.url` /
  `session.bind.url` intact, and `get_postgres_checkpoint_url()` refuses a URL that already arrived
  masked instead of connecting with `***` - the failure then names the lost password rather than
  looking like a wrong one. `hobees/db/backends.py`, `hobees/core/hive_builder.py`,
  `hobees/cli/shell.py`, `hobees/cli/main.py`, `hobees/core/queen.py`.
- Web UI: a model that is visibly selected in the Bee and Hive dialogs is now also the value the
  form holds. When a provider had no "default_model", the picker showed its first detected
  model while the form value stayed empty, so saving said "Pick or type a model name" and
  **Test model** stayed disabled even though a model looked chosen - and the Workbench path worked
  because the backend resolved the model itself. The Bee and Hive dialogs now resolve the model the
  same way the picker displays it ("pickModel": requested, provider default, assistant model,
  first detected), so the value on screen is the value that gets saved and Test model is enabled
  whenever a model is known.
  "POST /api/v1/bees" /
  "POST /api/v1/hives" resolve a blank model the same way ("resolve_model_name") and refuse a
  provider with nothing to use instead of storing a row the runtime would fail on.
  (default, assistant, or the first detected one).
- Reset: `hobees.db` is now actually removed. `configured_database_file()` falls back to
  the default `~/.hobees/hobees.db` when the env file carries no `HOBEES_DATABASE_URL`
  (the state a previous reset leaves behind), and `apply_plan()` releases the SQLAlchemy
  engine pool before deleting, so the Studio panel and any in-process reset no longer
  fail with `WinError 32` on Windows. A file held open by another process is still
  reported rather than forced, and the CLI now names the paths left behind instead of
  claiming the slate is clean.
- Containers: the Postgres service key and the host name in the generated database URL are now the
  same value (`postgres_service_name`), the `db` hardcode is gone, every host path is written
  relative to the compose file ("./" prefix: `./artifacts`, `./skills`, `./goal.txt`, `./.env`,
  `./Dockerfile`), and a path is defined exactly once - `HOBEES_CONFIG_PATH` and
  `HOBEES_GOAL_FILE` come from the `Dockerfile` "ENV" and the entrypoint script reads them from
  the environment, so the compose "environment:" block no longer repeats them. In stdin mode no
  goal path is defined at all, because there is no goal file.
- Fixed: the generated Dockerfile installed the project from source instead of PyPI, published
  `8420` instead of the new `6543` default, and wrote `./C:/Users/...:/data/skills` for an absolute
  settings path (and the host name for `container_name`) — generated files now use relative paths
  and run-time names. `save_project_files()` takes the full generated set with validated plain file
  names, the goal mount is no longer duplicated when volumes are set, and the Containers tab refreshes
  the run command, config, entrypoint and goal when the settings change instead of showing the first
  plan.

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

