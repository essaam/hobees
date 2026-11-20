# hobees (alias `hobiz`)

**Hobees makes Bee and Hive workflows usable as repeatable command-line jobs, including in short-lived containers, while keeping an interactive shell and TUI available.** The name is inspired by honey bees. It is built with LangGraph; PostgreSQL is recommended for multi-process use, while SQLite is supported for local use.

---

## 🍯 Quick Start

```bash
# Install via uv (recommended)
uv tool install hobees

# Or from source
git clone https://github.com/essaam/hobees.git
cd hobees
uv sync
uv run hobees
```

### First Run

```bash
# 1. Configure a database
mkdir -p ~/.hobees
cp .env.example ~/.hobees/.env
# Choose SQLite or PostgreSQL by setting HOBEES_DATABASE_URL in ~/.hobees/.env.
# Export any provider API key named by api_key_env, e.g. OPENAI_API_KEY.

# 2. Initialize database tables
hobees init

# 3. Enter the interactive subshell
hobees
🍯 hobees > /provider add          # Register an LLM provider
🍯 hobees > /bee create            # Create a Worker Bee
🍯 hobees > /hive create           # Create a Working Hive (team)
🍯 hobees > /goal build a landing page   # Run goal through the dynamic-Hive handler

# 4. Single-shot mode
hobees -p "summarize the latest docs"
```

---

## 📖 Table of Contents

- [Architecture Overview](#architecture-overview)
- [Core Concepts](#core-concepts)
- [Interactive Shell](#interactive-shell)
- [CLI Commands](#cli-commands)
- [Configuration](#configuration)
- [Docker Compose](#docker-compose)
- [Multi-Terminal & Web API](#multi-terminal--web-api)
- [Feature Highlights](#feature-highlights)
- [Development](#development)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                      hobees CLI                                │
├────────────────────────────────────────────────────────────────┤
│  Interactive Shell (/slash commands)    │   Typer Subcommands  │
├─────────────────────────────────────────┼──────────────────────┤
│  Queen Agent Component                  │                      │
│  ─────────────────────────────────      │                      │
│  • inspect_roster()                     │                      │
│  • form_and_run_hive(goal, bees)        │                      │
├─────────────────────────────────────────┼──────────────────────┤
│  Working Hive (Supervisor + Workers)    │                      │
│  ─────────────────────────────────      │                      │
│  • Hive Supervisor (create_agent)       │                      │
│  • Worker Bees (create_agent)           │                      │
│  • PostgreSQL / SQLite checkpoints      │                      │
├─────────────────────────────────────────┼──────────────────────┤
│  Core Services                          │                      │
│  ┌──────────────┐ ┌──────────────────┐  │                      │
│  │ LLM Factory  │ │ Tool Registry    │  │                      │
│  │ (providers)  │ │ (read_file, etc) │  │                      │
│  └──────────────┘ └──────────────────┘  │                      │
│  ┌──────────────┐ ┌──────────────────┐  │                      │
│  │ Telemetry    │ │ Context Manager  │  │                      │
│  │ (callbacks)  │ │ (compaction)     │  │                      │
│  └──────────────┘ └──────────────────┘  │                      │
│  ┌──────────────┐ ┌──────────────────┐  │                      │
│  │ Memory Mgr   │ │ Skill Harvester  │  │                      │
│  │ (scoped)     │ │ (self-learn)     │  │                      │
│  └──────────────┘ └──────────────────┘  │                      │
├─────────────────────────────────────────┼──────────────────────┤
│  PostgreSQL / SQLite Database           │                      │
│  ┌──────────────┐ ┌──────────────────┐  │                      │
│  │ Providers    │ │ Bees             │  │                      │
│  │ Bees/Hives   │ │ Memories/Skills  │  │                      │
│  │ Runs/Usage   │ │ Checkpoints      │  │                      │
│  └──────────────┘ └──────────────────┘  │                      │
└─────────────────────────────────────────┴──────────────────────┘
```

### Two Orchestration Layers

| Layer | Role | Component |
|-------|------|-----------|
| **Meta-Orchestration** | Queen agent inspects the roster and can create a dynamic hive; the current `/goal` handler creates one directly | **Queen Meta-Orchestrator** (separate agent, not a bee) |
| **Hive Orchestration** | Delegates subtasks to worker bees within a specific hive | **Hive Supervisor** (configured per-hive, separate from bees) |

> **Note:** The **Queen** and **Hive Supervisor** are *orchestration agents*, not worker bees. They route work and synthesize results. A hive's supervisor is configured with its own provider/model/prompt, independent of its member bees.

---

## Core Concepts

### 🔌 LLM Providers
Global registry of LLM endpoints shared across all Bees and Hives.
- **Types**: `openai`, `anthropic`, `google_genai`, `openai_compatible` (Ollama, vLLM, LM Studio, OpenRouter, Groq, etc.)
- **Security**: Stores only the environment variable name for API keys (`api_key_env`), never plaintext secrets
- **Cost tracking**: Optional `input_cost_per_1m` / `output_cost_per_1m` for real-time cost estimation

```bash
/provider add
# or
hobees provider add --interactive
```

### 🐝 Worker Bees
Reusable AI agents that exist independently of Hives. A Bee can belong to multiple Hives simultaneously.
- **Attributes**: name, role_description, system_prompt, provider, model, temperature, thinking_level, tool_names
- **Thinking levels**: `off` | `low` | `medium` | `high` (provider-normalized)

```bash
/bee create "coder" "Writes production code" "You are a senior engineer..." provider-id gpt-4o-mini 0.0 "read_file,write_file,list_directory" --thinking medium
```

### ⬡ Working Hives
Teams of Bees under a **Hive Supervisor** (many-to-many relationship via `hive_memberships`).
- **Supervisor**: Has its own provider, model, prompt, and thinking level (configured at hive creation)
- **Static Hives** (`is_dynamic=false`): User-created, reusable teams
- **Dynamic Hives** (`is_dynamic=true`): Created for one-off goals; the `/goal` handler creates a new one for each run
- **Project Path**: Optional subdirectory under the project root for file-based work

```bash
/hive create "dev-team" --supervisor-provider openai --supervisor-model gpt-4o
/hive add-bee dev-team coder
/hive add-bee dev-team reviewer
```

### 👑 Queen Meta-Orchestrator Component
The Queen agent implementation can inspect the global roster and select Bees for a goal. Its `form_and_run_hive` tool always creates a new dynamic Hive; it does not execute or reuse an existing static Hive. The interactive shell's `/goal` handler currently creates and runs a dynamic Hive directly rather than invoking the Queen agent.
- **Tools**: `inspect_roster()`, `form_and_run_hive(goal, bee_names)`
- **Session override**: `/thinking <level>` applies to all Bees in the run
- **Not a bee** — it's a separate orchestration agent that manages hive creation

---

## Interactive Shell

Running `hobees` with no arguments drops you into the interactive shell with slash-command autocomplete. Run `hobees --tui` to use the alternate TUI. In either interface, type `@` followed by a path prefix to browse the current folder. Use Up/Down to select a suggestion and Enter to insert its path; folders can be browsed by adding `/` to the path. The picker includes `..` for the parent directory and displays at most four rows. The selected path is added to your message as text; Hobees does not automatically read or attach the file contents.

### Prompt States

| Prompt | Meaning |
|--------|---------|
| `🍯 hobees > ` | Default assistant chat and slash-command mode |
| `🍯 (hobees:dev-team) > ` | Locked to Hive "dev-team" |

### Slash Commands

| Command | Description |
|---------|-------------|
| `/provider add \| list \| test \| remove \| models <alias> [--refresh] \| use <alias\|number>` | Manage LLM providers. `models` only **lists** the models a provider exposes; `use` **switches** the session to that provider |
| `/assistant show \| use <provider> [model] \| model [name]` | Configure the default assistant (the agent you chat with). The choice is saved and reused on every launch, so you are not asked again |
| `/bee create \| list \| update \| delete \| thinking <name> <level>` | Manage Worker Bees |
| `/hive create \| add-bee \| remove-bee \| list \| remove \| use <name> \| auto \| thinking <name> <level> \| artifacts [name] \| trace [name]` | Manage Working Hives. `/hive remove` lets you select multiple hives by list number |
| `/chat bee <name> \| hive <name> \| list` | Direct chat with Bee or Hive |
| `/goal <goal>` | Run a goal by creating a dynamic Hive; does not reuse a static Hive |
| `/usage [all\|bee\|hive\|provider\|day] [--window 1h\|24h\|7d\|all]` | Query usage telemetry |
| `/thinking <off\|low\|medium\|high\|auto>` | Session-wide thinking level override |
| `/compact` | Compress active thread's message history |
| `/memory list\|add\|forget\|show [--namespace global\|hive:<name>\|bee:<name>]` | Cross-session scoped memory |
| `/skill list\|show\|create\|save-last\|assign\|unassign\|sync` | Progressive skill library |
| `/session save\|load\|list\|delete <name>` | Named session management |
| `/help` | Show all commands |
| `/quit` or `/exit` | Exit shell |

### Example Session

```text
🍯 hobees > /provider add
Provider alias: openai-main
Provider type: openai
API key env var (or NONE): OPENAI_API_KEY
Default model: gpt-4o-mini
✅ Provider openai-main (openai) registered

🍯 hobees > /bee create
Bee name: researcher
Role description: Web researcher and summarizer
System prompt: You are a thorough researcher. Use tools to gather and synthesize info.
Provider: openai-main
Model name: gpt-4o-mini
Temperature: 0.3
Tool names: read_file,write_file,list_directory,run_python_calc
Thinking level: medium
✅ Bee researcher created

🍯 hobees > /hive create
Hive name: research-team
Goal description: Research and summarize topics
Supervisor provider: openai-main
Supervisor model: gpt-4o
Supervisor thinking: high
✅ Hive research-team created

🍯 hobees > /hive add-bee research-team researcher
✅ Bee researcher added to Hive research-team

🍯 hobees > /hive use research-team
✅ Switched to Hive: research-team

🍯 (hobees:research-team) > Research the latest Rust async patterns and write a summary
⬡ Hive Supervisor delegating to researcher...
🐝 researcher: [uses tools, writes file]
✅ Hive completed. Summary written to artifacts/research-team/output/rust-async-summary.md
📊 Run: 2,840 in / 1,200 out tokens • $0.0084 • 3 LLM calls
```

In the TUI and shell, `/hive remove` shows a numbered hive list and lets you select multiple hives by number. TUI output supports terminal-native mouse selection and copy.

---

## CLI Commands

Common provider, Bee, Hive, memory, skill, and run operations are also available as direct Typer subcommands for scripting. Some slash commands are interactive-shell features only.

```bash
# Provider management
hobees provider add --interactive
hobees provider list
hobees provider test openai-main
hobees provider models openai-main --refresh

# Bee management
hobees bee create researcher "Web researcher" "You are..." 1 gpt-4o-mini --tool-names "read_file,write_file" --thinking medium
hobees bee list
hobees bee update researcher --model gpt-4o --thinking high
hobees bee delete researcher

# Hive management
hobees hive create research-team 1 --goal "Research tasks" --supervisor-model gpt-4o --thinking high
hobees hive add-bee research-team researcher
hobees hive list
hobees hive remove research-team --yes

# Headless execution and resumable threads
hobees hive run research-team "Research Rust async patterns" --thread rust-async-1 --json
# Equivalent root command:
hobees run --hive research-team "Research Rust async patterns" --quiet

# Declarative setup and direct interactive hive launch
hobees init --config ./hobees.yaml
HOBEES_CONFIG_PATH=./hobees.yaml hobees hive list
hobees shell --hive research-team

# Memory management
hobees memory list --namespace global
hobees memory add user_prefers_typescript "User prefers TypeScript over JavaScript" --namespace global
hobees memory show user_prefers_typescript --namespace global

# Skill management
hobees skill list
hobees skill create --name rust-async-patterns --description "Research Rust async patterns" --from-file ./skill.md
hobees skill assign rust-async-patterns researcher

# Single-shot execution
hobees -p "summarize the latest docs"

# Local API server
hobees serve --port 8420

# Usage summary
hobees stats --window 24h --group-by hive
```

---

## Configuration

Application settings are loaded from `~/.hobees/.env` (or local `.env`) with the `HOBEES_` prefix. PostgreSQL is recommended for multi-process use; SQLite is also supported for local/single-user use.

### Database and startup configuration

| Variable | Description |
|----------|-------------|
| `HOBEES_DATABASE_URL` | Database URL, e.g. `postgresql+psycopg://user:pass@localhost:5432/hobees` or `sqlite:///./hobees.db` |
| `HOBEES_CONFIG_PATH` | Optional YAML/JSON config file to synchronize automatically before normal CLI commands |
| `HOBEES_ARTIFACTS_ROOT` | Root directory for per-hive run artifacts (default: `./artifacts`) |

### Choosing SQLite or PostgreSQL

Set `HOBEES_DATABASE_URL` in `~/.hobees/.env` or the project `.env`. This URL
selects the database for both Hobees application data and LangGraph checkpoints;
there is no interactive database chooser.

For a local, single-user setup, use file-backed SQLite:

```dotenv
# Add to ~/.hobees/.env or the project .env:
HOBEES_DATABASE_URL=sqlite:///./hobees.db
```

```bash
uv run hobees init
```

The relative SQLite path is resolved from the working directory where Hobees
runs. Use an absolute SQLite URL if commands will run from different
directories. File-backed SQLite keeps data and checkpoints between runs;
`sqlite:///:memory:` is temporary and is not suitable for persistent use.
SQLite is intended for local/single-user use and does not provide PostgreSQL's
concurrent multi-process behavior.

For multi-process use, use PostgreSQL:

```dotenv
# Add to ~/.hobees/.env or the project .env:
HOBEES_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/hobees
```

```bash
uv run hobees init
```

The PostgreSQL server and database must already exist. URL-encode special
characters in usernames or passwords. PostgreSQL is also the database used by
the Docker Compose example below.

Changing `HOBEES_DATABASE_URL` switches to a separate database; it does not
copy or migrate existing data between SQLite and PostgreSQL.

### Optional (with defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `HOBEES_QUEEN_PROVIDER` | `openai` | Default Queen provider alias |
| `HOBEES_QUEEN_MODEL` | `gpt-4o-mini` | Default Queen model |
| `HOBEES_API_HOST` | `127.0.0.1` | FastAPI bind host |
| `HOBEES_API_PORT` | `8420` | FastAPI bind port |
| `HOBEES_LOG_LEVEL` | `INFO` | Application log level |
| `HOBEES_COMPACTION_THRESHOLD` | `0.65` | Fraction of context window before compaction |
| `HOBEES_MAX_TOOL_OUTPUT_CHARS` | `8000` | Max chars for tool output before scratchpad offload |
| `HOBEES_ENABLE_AUTO_MEMORY` | `false` | After successful Hive runs, make an extra model call to save stable preferences globally and (for named Hives) durable Hive-specific facts |
| `HOBEES_SKILLS_DIR` | `~/.hobees/skills` | Directory for skill Markdown files |
| `HOBEES_TRACE_CONTENT_MODE` | `summary` | Trace message content: `metadata` (no message text), `summary` (short previews with best-effort secret redaction), or `full` (full messages with best-effort secret redaction). Tool argument and result values are never logged |

### Example `.env`

```bash
# ~/.hobees/.env
HOBEES_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/hobees
HOBEES_QUEEN_PROVIDER=openai-main
HOBEES_QUEEN_MODEL=gpt-4o-mini
HOBEES_API_PORT=8420
HOBEES_COMPACTION_THRESHOLD=0.7
HOBEES_MAX_TOOL_OUTPUT_CHARS=10000
HOBEES_ENABLE_AUTO_MEMORY=true
```

Provider credentials are read from the process environment using each provider's `api_key_env` value; application settings loaded from `.env` do not export those keys to the process.

`HOBEES_CONFIG_PATH` is synchronized on normal CLI startup. A config containing a `bees` list reconciles the hive's memberships to that list. Resources absent from the file are preserved. Use `hobees init --config PATH` for a one-time import without setting the startup variable.

### Running configured Hives headlessly

After installing Hobees and ensuring its executable is on your `PATH`, invoke it directly:

```bash
hobees init --config config-template.yaml
hobees hive run local-dev "Explain the tradeoffs of SQLite for local development" --json
```

When running from a source checkout, prefix these commands with `uv run`.

The `local-dev` example uses only its local llama.cpp supervisor and worker.
Start a compatible server reachable from the environment running Hobees at the
configured URL and expose the configured model name first. `is_dynamic`
classifies a Hive but does not cause automatic selection.
`hobees hive run <name> ...` runs that Hive directly without the Queen. Root
`hobees run` without `--hive` instead creates a one-off Hive with all registered
Bees available to its supervisor; because the template defines multiple
providers, that path also needs `--provider`. `/goal` likewise does not route
to a configured Hive.

---

## Docker Compose

The Compose template runs each Hobees command as a one-shot container and starts a private PostgreSQL service for it. It does not expose a database port or start an interactive shell by default.

```bash
cp .env.docker.example .env
# Edit .env: set a strong, URL-safe POSTGRES_PASSWORD and provider API keys.
mkdir -p artifacts skills
# On Linux, set HOBEES_UID and HOBEES_GID in .env to the output of `id -u` and `id -g`.

docker compose build
docker compose run --rm hobees init
docker compose run --rm hobees hive list
docker compose run --rm hobees hive run research-team "Summarize the project plan" --json
```

The `./artifacts` bind mount makes run outputs available on the host (worker-created files are under `artifacts/<hive>/output/`), and `./skills` persists Markdown skill files. The named `postgres_data` volume preserves providers, Bees, Hives, runs, memories, and checkpoints across container recreation and `docker compose down`. Remove the corresponding volume mappings from `compose.yaml` if persistence is not wanted. **`docker compose down -v` deletes the database volume and its contents.**

To load declarative setup, uncomment the optional `./config:/config:ro` mount in `compose.yaml`, set `HOBEES_CONFIG_PATH=/config/hobees.yaml` in `.env`, and place the config file in `./config`. You can instead run a one-time import with `docker compose run --rm hobees init --config /config/hobees.yaml`.

Provider API keys are passed into the runtime container from `.env`; they are not baked into the image. Add any custom API-key environment variables used by your providers to `.env`. The app container runs as the numeric user configured by `HOBEES_UID` and `HOBEES_GID` so it can write to the artifacts and skills bind mounts.

---

## Multi-Terminal & Web API

Because PostgreSQL handles concurrent reads/writes safely, usage insights are accessible from three surfaces simultaneously:

### 1. In-Session Live Ticker
After every run, a concise footer prints:
```
tokens: 2,840 in / 1,200 out • $0.0084 • 3 LLM calls
```

### 2. Concurrent Second Terminal
```bash
# Query usage from a separate terminal
hobees stats --window 24h --group-by hive
```
The command prints an aggregate table; it does not run a watch dashboard.

### 3. Local Web API
```bash
hobees serve --port 8420
```
Launches FastAPI at `http://127.0.0.1:8420` with endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Service and database status |
| `GET /api/roster` | Providers, Bees, and Hives |
| `GET /api/runs` | Run history, optionally filtered by status |
| `GET /api/runs/active` | Active runs |
| `GET /api/runs/{thread_id}` | Run details and trace |
| `GET /api/runs/{thread_id}/stream` | SSE trace replay and live updates |
| `GET /api/stats` | Aggregated usage (`?group_by=bee\|hive\|provider\|day&window=24h`) |
| `GET /api/stats/recent` | Recent usage events |
| `GET /api/usage/stream` | SSE usage events |

---

## Feature Highlights

### 🤖 Provider Model Auto-Discovery
Fetch available models from local (llama.cpp, Ollama, vLLM, LM Studio) or remote (OpenAI, Anthropic, Gemini, OpenRouter) providers.

```bash
/provider models openai-main --refresh
# or during /bee create, /hive create - interactive model picker appears
```

### 💭 Configurable Thinking Levels
Normalized `thinking_level` (`off` | `low` | `medium` | `high`) per Bee, Hive Supervisor, or session override.

| Provider | `off` | `low` | `medium` | `high` |
|----------|-------|-------|----------|--------|
| OpenAI | no reasoning_effort | `low` | `medium` | `high` |
| Anthropic | no thinking | 1024 tokens | 4096 tokens | 16384 tokens |
| Google GenAI | thinking_budget=0 | 1024 | 8192 | 24576 |
| llama.cpp / OpenRouter | reasoning_effort=none, enable_thinking=false | `low` | `medium` | `xhigh` |

```bash
/thinking medium           # Session override
/bee thinking researcher high    # Persist to Bee
/hive thinking research-team high # Persist to Hive Supervisor
```

### 🗜️ Context Efficiency Engine
Four controls to prevent quadratic token growth:

1. **Worker Context Isolation** - Bees receive clean projected context (system prompt + scoped memories + skill headers + subtask), not the raw supervisor message history
2. **Tool Output Truncation** - Large hive tool outputs are saved under the active project/artifact root, typically `artifacts/<hive>/scratchpad/<thread_id>/`; a preview is returned
3. **Rolling Conversation Compaction** - At the configured context threshold (65% by default), older messages are locally summarized into `running_summary`; no summarizer-model call is made, and the last four messages are retained verbatim
4. **Progressive Skill Loading** - Only skill headers (`name: description`) injected; full instructions loaded on-demand via `load_skill` tool

```bash
/compact  # Manual compaction
```

### 🧠 Cross-Session Scoped Memory
Three namespaces persisted in the configured database:

| Namespace | Scope |
|-----------|-------|
| `global` | User preferences, facts across all sessions |
| `hive:<name>` | Project-specific context shared within a hive |
| `bee:<name>` | Bee-specific learned patterns |

The Queen receives global memories; Hive supervisors receive global and Hive-scoped memories; workers receive global, Hive-scoped, and their own Bee-scoped memories. Memories are loaded when each agent is built. Enable `HOBEES_ENABLE_AUTO_MEMORY=true` to make an additional call to the configured supervisor model after successful Hive runs. It extracts stable preferences into `global` and, for named Hives, durable project facts into `hive:<name>`. Ephemeral Hives save only global preferences. The default is off; enabling it sends the goal and final result to the configured model and may incur extra usage. Extraction is best-effort, so review saved entries with `hobees memory list` and remove incorrect ones with `hobees memory forget`.

```bash
/memory add global user_prefers_typescript "Prefers TypeScript"
/memory add hive:dev-team project_uses_fastapi "Backend is FastAPI"
/memory list hive:dev-team
```

### 📜 Progressive Skill Library
Reusable procedural skills stored in the configured database with Markdown sync (`~/.hobees/skills/*.md`).

```bash
/skill create              # Interactive wizard
/skill save-last           # Persist skill draft from last run
/skill assign skill-name bee-name
/skill sync                # Import from Markdown files
```

Skills injected as metadata headers; full instructions loaded via `load_skill` tool.

### 🔄 Skill Drafts from Completed Hive Runs
After a successful Hive run with at least four tool calls or an estimated two handoffs, Hobees makes an additional call to the Hive Supervisor's configured model to look for a reusable procedure. The handoff count is approximated from distinct Bees that used the model. A generated draft is saved on the run record, not automatically added to the skill library.

This applies to Queen-created and one-off Hives, `/goal`, named headless runs such as `hobees hive run dev-team "..." --json`, and interactive Hive chats in the shell or TUI. Interactive shell runs offer to save or edit the draft; the TUI displays a notice, and headless JSON includes `suggested_skill_draft` in the run manifest. Use `hobees skill save-last` from the CLI to review and save a stored draft. The reflection call may incur additional model charges and is not currently included in run usage telemetry.

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributor guidance and test instructions.

### Prerequisites
- Python 3.11+
- PostgreSQL 15+ (recommended for multi-process use; file-backed SQLite is supported for local use)
- `uv` (package manager)

### Setup
```bash
git clone https://github.com/essaam/hobees
cd hobees
uv sync

# Configure PostgreSQL (recommended) or SQLite
mkdir -p ~/.hobees
cp .env.example ~/.hobees/.env
# Set HOBEES_DATABASE_URL and export provider API keys in the process environment.

# Initialize
uv run hobees init
```

### Project Structure
```text
hobees/
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── .env.example
├── .env.docker.example
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
└── src/hobees/
    ├── __init__.py
    ├── config.py              # Pydantic settings
    ├── db/
    │   ├── session.py         # SQLAlchemy engine and session management
    │   ├── models.py          # SQLAlchemy ORM models
    │   └── analytics.py       # Fast SQL aggregations for usage insights
    ├── core/
    │   ├── llm_factory.py     # Resolves providers → LangChain ChatModels
    │   ├── telemetry.py       # LangChain CallbackHandler (live tokens/cost)
    │   ├── tool_registry.py   # Built-in @tool functions + registry
    │   ├── hive_builder.py    # Builds a StateGraph with create_agent workers and supervisor
    │   ├── queen.py           # Meta-Orchestrator agent
    │   ├── model_discovery.py # Auto-fetch models from providers
    │   ├── context_manager.py # Worker projection, compaction, scratchpad
    │   ├── memory_manager.py  # Scoped memory retrieval & reflection
    │   └── skill_harvester.py # Skill-draft extraction for completed Hive runs
    ├── api/
    │   └── app.py             # FastAPI app (endpoints + SSE)
    └── cli/
        ├── main.py            # Typer entrypoint; no measured cold-start target
        ├── shell.py           # prompt_toolkit REPL + slash commands
        ├── tui.py             # Optional prompt_toolkit split-pane TUI
        ├── icons.py           # Unicode/ASCII icon registry
        ├── provider_cmd.py    # Provider handlers (CLI + shell)
        ├── bee_cmd.py         # Bee handlers (CLI + shell)
        ├── hive_cmd.py        # Hive handlers (CLI + shell)
        ├── memory_cmd.py      # Memory handlers (CLI + shell)
        └── skill_cmd.py       # Skill handlers (CLI + shell)
```

### Adding Custom Tools
1. Add a new `@tool` function in `core/tool_registry.py`
2. Register it in `TOOL_REGISTRY`
3. Bees can now reference it by key in `tool_names`

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.