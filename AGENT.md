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

The Studio **Containers** tab prepares that deployment from the running settings:
it generates `compose.yaml` and `Dockerfile`, can save them to the project root
(`HOBEES_PROJECT_ROOT`, fixed file names) or export them, and can run the
allowlisted `docker compose up|down|ps|logs` actions. Environment values stay as
`${NAME}` references, so generated files never contain a key, and the actions are
blocked in `--read-only` mode or when `docker` is not installed.

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
  name** (`${NAME}`), never literal secret values, and the web layer runs only allowlisted
  `docker compose` subcommands (`up`, `down`, `ps`, `logs`) with fixed argv — no shell, no
  arbitrary arguments. `hobees.core.container_prep.ALLOWED_ACTIONS`, the endpoint check and
  `tests/test_container_prep.py` must agree.
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
