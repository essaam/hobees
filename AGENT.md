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
cp .env.example .env
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

Keep `./artifacts` and `./skills` mounted when testing features that write files. On Linux, set `HOBEES_UID` and `HOBEES_GID` in `.env` to match the host user (`id -u`, `id -g`) so bind mounts remain writable.

## Change Guidelines

- Follow existing Python, Typer, Pydantic, SQLAlchemy, and LangGraph patterns.
- Use focused edits and preserve public CLI behavior.
- Put orchestration logic in `src/hobees/core/`, persistence in `src/hobees/db/`, and CLI/API presentation in their respective packages.
- Add or update pytest coverage for new behavior and bug fixes.
- Update README sections and examples when user-visible behavior changes.
- Do not log or persist provider credentials.
- Do not alter or delete existing user data, database volumes, or unrelated generated files.

## Pull Requests

Before opening a pull request:

1. Rebase or merge the latest `main`.
2. Run targeted tests and the full pytest suite.
3. Verify Docker commands if Compose or the image is affected.
4. Describe the user-visible change, implementation summary, and test evidence.
5. Keep the diff focused and avoid unrelated cleanup.
