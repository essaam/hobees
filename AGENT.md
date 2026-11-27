# Agent Guide

This guide helps AI coding agents understand and work with the hobees repository.

## Repository Overview

Hobees is a Python CLI and FastAPI application built with LangGraph. It uses SQLAlchemy with PostgreSQL or SQLite and is managed with `uv`.

- `src/hobees/cli/` - Typer commands, interactive shell, TUI, and CLI configuration
- `src/hobees/core/` - Queen orchestration, hives, LLM providers, tools, memory, skills, telemetry, and context management
- `src/hobees/db/` - SQLAlchemy models, database setup, sessions, and analytics
- `src/hobees/api/` - FastAPI endpoints and server-sent event streams
- `tests/` - pytest coverage
- `Dockerfile` and `compose.yaml` - Container build and PostgreSQL runtime

## Local Setup

Use Python 3.11 or newer and install `uv`.

```bash
uv sync
uv run hobees init
```

Hobees defaults to `~/.hobees/hobees.db` for local, single-user use and writes
the platform-specific SQLite URL to `~/.hobees/.env` if no database URL is
configured. The interactive shell initializes a fresh database automatically.
Use `uv run hobees init` to initialize it explicitly before other
database-backed commands or to run migrations. To choose a different database, set
`HOBEES_DATABASE_URL` in `.env`; use
`postgresql+psycopg://user:password@localhost:5432/hobees` for PostgreSQL and
multi-process use. The same URL is used for application data and LangGraph
checkpoints. Changing the URL does not copy existing data to the other database.

SQLite file paths are relative to the process working directory. File-backed
SQLite persists checkpoints; `sqlite:///:memory:` is temporary. Do not use
SQLite as a shared multi-process database. Provider API keys must be set in the
process environment; providers store only their environment-variable names,
not secret values.

Never commit `.env`, API keys, local database files, generated artifacts, or skill outputs.

## Common Commands

```bash
uv run pytest
uv run pytest tests/test_hive_builder.py
uv run hobees --help
uv run hobees init
uv run hobees hive list
uv run hobees serve --port 8420
```

Run the smallest relevant test set while iterating, then run the complete suite before finalizing a change.

The PostgreSQL integration test creates and drops a unique schema in the
configured database. Point it only at a disposable test database:

```bash
HOBEES_TEST_POSTGRES_URL=postgresql+psycopg://user:password@localhost:5432/hobees_test \
  uv run pytest tests/test_database_backends.py
```

## Docker Workflow

Docker Compose is the supported containerized PostgreSQL workflow.

```bash
cp .env.docker.example .env
# Set POSTGRES_PASSWORD and any provider API key variables.
mkdir -p artifacts skills
docker compose build
docker compose run --rm hobees init
docker compose run --rm hobees hive list
docker compose run --rm hobees hive run research-team "Summarize the project plan" --json
```

The database password is required and `.env` is not committed. Use a URL-safe password because Compose includes it in `HOBEES_DATABASE_URL`.

The production Docker image is built with `uv sync --no-dev`, so it does not
include pytest. Run tests from the development checkout with `uv run pytest`.
This repository does not define a development Docker image.

The Studio **Containers** tab prepares that deployment from the running settings: it generates the
deployable set (`compose.yaml`, `Dockerfile`, `hobees.yaml`, `goal.txt`, `docker-entrypoint.sh`),
can save the files to the project root (`HOBEES_PROJECT_ROOT`, fixed names) or download them one
by one, and it does nothing else - nothing in hobees runs `docker` from the browser.
Environment values stay as `${NAME}` references, so generated files never contain a key, and the
write is blocked in `--read-only` mode.

Keep `./artifacts` and `./skills` mounted when testing features that write files. On Linux, set `HOBEES_UID` and `HOBEES_GID` in `.env` to match the host user (`id -u`, `id -g`) so bind mounts remain writable.

## Change Guidelines

- Follow existing Python, Typer, Pydantic, SQLAlchemy, and LangGraph patterns.
- Path segments derived from a namespaced thread key (trace JSONL names, the
  scratchpad directory for offloaded tool output) go through
  `hobees.core.paths.safe_path_component()` so they remain legal on Windows and
  the path a Bee is shown is the path it can read back. Tool path resolution
  reports `ERROR:` instead of raising for a path that cannot exist on the host.
- Use focused edits and preserve public CLI behavior.
- Put orchestration logic in `src/hobees/core/`, persistence in `src/hobees/db/`, and CLI/API presentation in their respective packages.
- Add or update pytest coverage for new behavior and bug fixes.
- Update README sections and examples when user-visible behavior changes.
- A `require_approval` gate can only fire for a tool the Bee declares in `tools`
  *and* that exists in `TOOL_REGISTRY`; `hobees import`, `hobees bee create`/`update`
  and the shared Bee handlers warn when it does not, because such a gate can never
  be reached. `hobees approvals`/`/approvals` and the Web UI show pending gates;
  `strict` resolves them by rejection without prompting, by design.
- Container preparation (Studio Containers tab) generates `compose.yaml` and `Dockerfile`
  from the live settings/providers. Generated files reference environment variables **by
  name** (`${NAME}`), never literal secret values, and no `docker` command is executed by the
  web layer: the tab writes files and the pipeline (or a person) runs them. The **exit code** is
  the pipeline's signal - 0 completed, 1 failed, 2 stopped for an approval a headless run cannot
  answer, 3 still running - so `docker-entrypoint.sh` must keep `set -eu` and the final `exec`,
  and `hobees.core.pipeline_status.STATUS_EXIT_CODES`, the manifest `exit_code`,
  `hobees pipeline status`, the entrypoint comment and `tests/test_pipeline_status.py` must agree.
  A run that ends awaiting approval must not exit 0. The Containers tab generates the deployable set
  from the active configuration (`compose.yaml`, `Dockerfile`, `hobees.yaml`, `goal.txt`,
  `docker-entrypoint.sh`): the entrypoint runs `hobees init --config` first, then the goal. The
  goal text is only ever written to its own file or read from stdin - it is never interpolated
  into the script - and `save_project_files()` takes plain validated file names inside the
  project root. `GOAL_MODES` (`mount` default, `bake`, `stdin`) must stay in sync with the
  generated command, the volume mount, and `tests/test_container_prep.py` / `tests/test_web.py`.  The `Dockerfile` generator must stay in step with the repo `Dockerfile` (PyPI install via
  `uv tool install hobees`, no source tree in the image) and `DEFAULT_WORKING_DIR` must stay equal to
  its `WORKDIR`. Generated paths are relative to the project root and run-time names are used
  (`CONTAINER_NAME_PLACEHOLDER`) so a machine-specific path or host name can never be written into a
  committed file; the web service is optional and commented out unless `include_web` is set.
  A path or value is defined once: the `Dockerfile` `ENV` provides `HOBEES_CONFIG_PATH` and
  `HOBEES_GOAL_FILE` and `docker-entrypoint.sh` reads them from the environment, so compose must not
  redefine them; the Postgres service key and the database host come from `postgres_service_name`; and
  every host path is written relative to the compose file (`./`). `.env.sample` lists key **names**
  only, never values, and must stay consistent with the names compose interpolates.
  In the Web UI, the model visibly selected must be the value the form stores: one order in the form
  ("pickModel") and the API ("resolve_model_name") - requested, provider default,
  assistant model, first detected, otherwise nothing. If the form holds an empty value while the picker
  shows one, saving reports "no model" and Test model stays disabled - that was the bug.
  saving a Bee or Hive says "add a model" and Test model stays disabled while one looks chosen. The API uses the same order ("resolve_model_name"): asked-for,
  default, assistant, first detected, and a provider with none of those is refused.
  The generator writes no `CMD` and no default compose `command`: `docker-entrypoint.sh` is the only
  place that decides what runs, and `spec.command` is an explicit override. The Containers tab is
  file-generation only - it must not offer to start or stop a container - and a field change reaches
  the files only through Update spec.
- An import writes by name, so `hobees import` and the Studio templates panel share
  `cli/import_cmd.CONFLICT_MODES` (`skip` | `overwrite`): `analyze_config_conflicts()` is
  the single source for what already exists, `overwrite` stays the CLI default, the web
  panel defaults to `skip`, and a colliding template is applied only after the user
  confirms. A skipped hive or skill keeps its roster and assignments too, since those are
  part of the entry.
- Reset (`hobees reset`, Studio Quick setup tab) deletes only the paths it planned: the config
  files inside `~/.hobees`, plus the skills/artifacts roots for `--all`. Confirmation is
  required on both surfaces — the CLI needs a `Y (yes)` answer and the API rejects an
  unconfirmed request — so `hobees.core.reset.allowed_roots()`, the plan builder and
  `tests/test_reset.py` must agree. `apply_plan()` releases the engine pool before it
  deletes, so a reset running inside a process that opened the database can remove
  `hobees.db` on Windows; a handle held by another process is reported, never forced.
  `reset` stays out of the slash-command catalog
  because the interactive shell and the TUI do not offer it.

## Pull Requests

Before opening a pull request:

1. Rebase or merge the latest `main`.
2. Run targeted tests and the full pytest suite.
3. Verify Docker commands if Compose or the image is affected.
4. Describe the user-visible change, implementation summary, and test evidence.
5. Keep the diff focused and avoid unrelated cleanup.
