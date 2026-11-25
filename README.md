# hobees (alias `hobiz`)

[![PyPI version](https://img.shields.io/pypi/v/hobees.svg)](https://pypi.org/project/hobees/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/essaam/hobees.svg)](LICENSE)

**Declarative (config-driven), CLI-first multi-agent orchestration built on LangGraph.**

_Hobees makes Bee and Hive workflows usable as repeatable command-line jobs, including in short-lived containers, while keeping an interactive shell and TUI available._ The name is inspired by honey bees. PostgreSQL is recommended for multi-process use, while SQLite is supported for local use.

**Web app:** `hobees web` serves the bundled React SPA on `http://127.0.0.1:6543` — Workbench, Studio, Runs & Traces and Memory & Artifacts: live run streams over SSE, HITL approvals you can resolve in the browser, on-demand provider detection, Quick setup templates and Reset. No Node runtime is needed, the built bundle ships inside the package. Details: [Web App](#-web-app).

## Why `hobees`?

Most multi-agent frameworks force you to write glue code to wire agents together, and then break down when you try to move from a local prototype to a reproducible pipeline. `hobees` treats agent teams as **portable, repeatable configuration**:

- **Interactive TUI + Headless CLI:** Prototype prompts and watch live delegation in the terminal, then run the exact same Hive non-interactively in GitHub Actions, cron jobs, or Docker workers.
- **Mix Local & Cloud Models per Agent:** Assign a high-reasoning frontier model (`thinking: high`) to your Supervisor while routing repetitive tasks to fast local models (`Ollama`, `llama.cpp`) or lightweight APIs.
- **Resumable Execution & Scoped Memory:** Backed by SQLite or PostgreSQL checkpoints (`--thread`), isolated workspace directories, and scoped memory (`global`, `hive`, or `bee` namespaces).
- **Self-Improving Workflows:** Capture successful multi-agent runs into reusable Markdown skills (`/skill save-last`) that future Hives automatically load.
- **Approval Gates & Container-Safe Threads:** Per-Bee `require_approval` tool lists enforced by a runtime policy (`interactive` \| `auto` \| `strict` \| `pause`), with every decision audited and every run keyed by a collision-free `<container>:<scope>:<entity>:<thread>` id for cross-container trace inspection and checkpoint replay.

## 🍯 Quick Start

```bash
# Install via uv (recommended)
uv tool install hobees

# Or from source
git clone https://github.com/essaam/hobees.git
cd hobees
uv sync
uv run hobees

# Launch the interactive CLI/TUI or run a single-shot headless job
hobees # CLI
hobees --tui
hobees -p "Summarize this directory"

# Or the web app on http://127.0.0.1:6543
hobees web --open
```

### Zero-Config Onboarding

The fastest path to a running hive is a single command.

```bash
# Scaffold a built-in template, import it, and you're ready to run
hobees init --template code-review    # OpenAI coder + Anthropic reviewer + planner
hobees init --template research       # OpenAI searcher + Gemini synthesiser
hobees init --template docs-writer    # OpenAI writer + editor
hobees init --template local-ollama   # Ollama on localhost:11434 — no API key needed
hobees init --template local-llamacpp # llama-server on localhost:8080 — no API key needed

# See all available templates
hobees init --list-templates

# Then run a hive immediately
hobees hive run dev-team "Review the changes in src/ and suggest improvements"
```

On **first launch with no providers configured**, hobees automatically scans your environment for available providers and offers to register them in one step:

- Cloud: checks `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`
- Local: probes `localhost:11434` (Ollama), `localhost:8080` (llama-server), `localhost:1234` (LM Studio)

The scan runs once and writes `~/.hobees/.detected` so it never fires again on subsequent launches.
To scan again later, run `hobees detect-providers` from a terminal or `/detect_providers` in the interactive shell. This explicit command always runs, regardless of the sentinel. In a headless environment, it skips confirmation and registers detected providers automatically.
Providers already in the registry are reported as already registered and are excluded from the new-provider list.

### Manual Setup (optional)

```bash
# 1. Optionally configure a database
# Set HOBEES_DATABASE_URL in ~/.hobees/.env to choose a database.
# Without it, Hobees uses local SQLite by default.
# Export any provider API key named by api_key_env, e.g. OPENAI_API_KEY.

# 2. Optionally initialize explicitly
hobees init

# 3. Enter the interactive subshell (initializes a fresh database automatically)
hobees
🍯 hobees > /provider add          # Register an LLM provider
🍯 hobees > /bee create            # Create a Worker Bee
🍯 hobees > /hive create           # Create a Working Hive (team)
🍯 hobees > /goal build a landing page   # Run goal through the dynamic-Hive handler

# 4. Single-shot mode
hobees -p "Summarize the docs in this workspace"
# or run an existing Hive headlessly
hobees run --hive dev-team --json "Add feature x to y"
```

---

## 📖 Table of Contents

- [Architecture Overview](#architecture-overview)
- [Core Concepts](#core-concepts)
- [Approval Gates (HITL)](#-approval-gates-hitl)
- [Interactive Shell](#interactive-shell)
- [CLI Commands](#cli-commands)
- [Web App](#-web-app)
- [Container-Aware Thread IDs & Trace Inspection](#-container-aware-thread-ids--trace-inspection)
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
┌─────────────────────────────────────────┐
│               hobees CLI                │
├─────────────────────────────────────────┤
│  Interactive Shell (/slash commands)    │
├─────────────────────────────────────────┤
│  Queen Agent Component                  │
│  ─────────────────────────────────      │
│  • inspect_roster()                     │
│  • form_and_run_hive(goal, bees)        │
├─────────────────────────────────────────┤
│  Working Hive (Supervisor + Workers)    │
│  ─────────────────────────────────      │
│  • Hive Supervisor (create_agent)       │
│  • Worker Bees (create_agent)           │
│  • Approval gate (tool middleware)      │
│  • PostgreSQL / SQLite checkpoints      │
├─────────────────────────────────────────┤
│  Core Services                          │
│  ┌──────────────┐ ┌──────────────────┐  │
│  │ LLM Factory  │ │ Tool Registry    │  │
│  │ (providers)  │ │ (read_file, etc) │  │
│  └──────────────┘ └──────────────────┘  │
│  ┌──────────────┐ ┌──────────────────┐  │
│  │ Telemetry    │ │ Context Manager  │  │
│  │ (callbacks)  │ │ (compaction)     │  │
│  └──────────────┘ └──────────────────┘  │
│  ┌──────────────┐ ┌──────────────────┐  │
│  │ Memory Mgr   │ │ Skill Harvester  │  │
│  │ (scoped)     │ │ (self-learn)     │  │
│  └──────────────┘ └──────────────────┘  │
│  ┌──────────────┐ ┌──────────────────┐  │
│  │ HITL gates   │ │ Approval events  │  │
│  │ (approval)   │ │ (audit store)    │  │
│  └──────────────┘ └──────────────────┘  │
├─────────────────────────────────────────┤
│  PostgreSQL / SQLite Database           │
│  ┌──────────────┐ ┌──────────────────┐  │
│  │ Providers    │ │ Bees             │  │
│  │ Bees/Hives   │ │ Memories/Skills  │  │
│  │ Runs/Usage   │ │ Checkpoints      │  │
│  │              │ │ Approval events  │  │
│  └──────────────┘ └──────────────────┘  │
└─────────────────────────────────────────┘
```

### Two Orchestration Layers

| Layer                  | Role                                                                                                            | Component                                                     |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| **Meta-Orchestration** | Queen agent inspects the roster and can create a dynamic hive; the current `/goal` handler creates one directly | **Queen Meta-Orchestrator** (separate agent, not a bee)       |
| **Hive Orchestration** | Delegates subtasks to worker bees within a specific hive                                                        | **Hive Supervisor** (configured per-hive, separate from bees) |

> **Note:** The **Queen** and **Hive Supervisor** are _orchestration agents_, not worker bees. They route work and synthesize results. A hive's supervisor is configured with its own provider/model/prompt, independent of its member bees.

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

- **Attributes**: name, role_description, system_prompt, provider, model, temperature, thinking_level, tool_names, `require_approval` (tools that must pass an [approval gate](#-approval-gates-hitl))
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

## 🔐 Approval Gates (HITL)

Tool sensitivity is declared **per Bee**; enforcement is a **runtime policy** resolved per run. A Bee lists which of its tools must pass a gate, and the runtime decides what happens when one of those tools is called.

```yaml
bees:
  - name: coder-bee
    provider: openai
    model: gpt-4o
    tools: [read_file, write_file]
    require_approval: [write_file]
```

- `require_approval` is a JSON column on the `bees` table (`hobees init` adds it to existing databases) and is reconciled by `hobees import` / `hobees init --config`. It can also be set with `hobees bee create --approval write_file`, `hobees bee update --approval write_file`, or the Studio Bee dialog.
- A gate only fires when three things line up: the tool is in the Bee's `tools` list, that tool is a **registered** tool, and the model actually calls it. `get_tools()` skips unknown names, so a gate on a name that is not in `TOOL_REGISTRY` can never fire — the built-in tools are `read_file`, `write_file`, `list_directory`, `run_python_calc`, `load_skill`, `save_memory`, `recall_memory`. `hobees import` and the shared Bee handlers warn when a gate names a tool that is missing from `tools` or is not registered.
- `strict` never asks: it rejects the gated call with a policy `ToolMessage`. Only `interactive` (and `pause`) create a pending approval. The Web UI polls pending approvals and shows a **Gate open on this run** card on the Workbench plus the Approvals drawer ([Web App](#-web-app)).

To see a gate fire end to end, create the Bee above (`hobees bee create gate-bee "writes files" "Use write_file when asked." 1 gpt-4o --tool-names write_file --approval write_file`), set the level to `interactive`, and prompt:

```text
Write the current date to report.txt in the output directory.
```

The run pauses at `TOOL_APPROVAL_REQUEST`, the run row becomes `awaiting_approval`, and the approval can be resolved from the Workbench card, the drawer, `hobees approvals`, or `POST /api/v1/approvals/{id}/resolve`.

### Levels

| Level         | What happens to a gated tool                                               | Process lifecycle                                          | Primary use                                    |
| ------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------- |
| `interactive` | `interrupt()` pauses the graph and prompts `[A]pprove / [E]dit / [R]eject` | stays alive waiting for the operator                       | local shell/TUI, `hobees hive run` on a TTY    |
| `auto`        | executes immediately, recorded as an auto-approval                         | runs start-to-finish without blocking                      | trusted containers, cron, CI/CD                |
| `strict`      | never executes; returns a policy-rejection `ToolMessage`                   | runs start-to-finish without blocking                      | read-only audit containers, untrusted Hives    |
| `pause`       | `interrupt()` + checkpoint, prints the JSON manifest, exits `0`            | container ends immediately; a later run resumes the thread | asynchronous sign-off for ephemeral containers |

### Precedence

The effective level is resolved in strict order (first match wins):

1. **CLI flag** — `--approval-mode <level>` (convenience alias `--auto-approve` → `auto`) on the root, `shell`, `run` and `prompt` commands. The flag seeds the session level for that run; a later `/approvals <level>` replaces it.
2. **Session override** — `/approvals <level>` in the shell or TUI, or `hobees approvals --session <level>` headless. Lives only for the current process.
3. **Saved global setting** — `HOBEES_APPROVAL_MODE` in `~/.hobees/.env`, written by `hobees approvals set <level>`.
4. **Context default** — `interactive` when stdin is a TTY, `strict` when headless (secure by default).

Values outside these four levels are ignored rather than trusted, so a bad setting can never widen a policy.

### Where the gate runs

`ApprovalMiddleware` wraps tool execution **inside the LangGraph graph** (on each worker's `create_agent`), not in an external loop around `.invoke()`. That keeps:

- the exact `interrupt()` / `Command(resume=...)` boundaries in the checkpointer, so `--replay <checkpoint_id>` works across gates;
- paired messages for every `AIMessage(tool_calls=[...])` — a rejection still returns a `ToolMessage`, so the Bee can recover rather than crash, and message-history validation stays valid;
- sequential evaluation when a Bee emits several gated tool calls in one turn.

Editing at a gate substitutes the approved arguments before execution and records the decision as `edit` with the original and final args; rejections record a reason. Every evaluation is written to `approval_events`, and a telemetry-store failure never weakens the gate.

### Setting the level

```text
🍯 hobees > /approvals                 # current level + where it comes from, plus the level legend
🍯 hobees > /approvals auto            # this session only
🍯 hobees > /approvals global strict   # persisted to ~/.hobees/.env
🍯 hobees > /approvals default         # clear the session override
```

`/permissions` is the alias of `/approvals` in both front-ends, and the completion menu and the handler accept exactly the same words. Headless the same resolver is exposed as `hobees approvals` (alias `hobees permissions`), with `--json` for scripted callers:

```bash
hobees approvals                       # show the effective level and its source
hobees approvals set auto              # persist globally
hobees approvals --session pause       # this run only, nothing saved
hobees approvals --json                # {"level": "...", "source": "...", "global": "...", "session": ...}
hobees approvals --help                # levels, usage and precedence explained
```

In `--json`, `level` is the effective level, `global` the persisted value, `session` the override for this run, and `source` the tier that won (`session override` / `global` / `context default`). Both the env var and the `.env` file report as `global`, and the CLI-flag tier is not reported separately.

The interactive prompt loop currently runs in `hobees hive run` (headless on a TTY); in shell/TUI chat turns `auto` and `strict` are enforced immediately, while an `interactive`/`pause` gate there is resumed with `hobees hive run --resume-decision`.

### Pause, exit, resume

```bash
# Container 1: a gated tool pauses the graph, the manifest is printed, exit 0
docker compose run --rm hobees hive run dev-team "Review src/" --thread pr-42 \
  --approval-mode pause --json
# → {"status": "awaiting_approval", "container": "coder-worker-1",
#    "thread": "coder-worker-1:hive:dev-team:pr-42", "pending_approvals": [...]}

# Container 2: same container name and thread, decision supplied from the operator
HOBEES_CONTAINER_NAME=coder-worker-1 hobees hive run dev-team "continue" --thread pr-42 \
  --resume-decision approve \
  --resume-args '{"command": "pytest tests/auth -k test_login"}' \
  --json
```

`--resume-decision` accepts `approve`, `edit` or `reject`, with `--resume-args` (JSON) for edits and `--resume-reason` for rejections, and the run status stays `awaiting_approval` while a gate is pending.

---

## Interactive Shell

Running `hobees` with no arguments drops you into the interactive shell with slash-command autocomplete. Run `hobees --tui` to use the alternate TUI. In either interface, type `@` followed by a path prefix to browse the current folder. Use Up/Down to select a suggestion and Enter to insert its path; folders can be browsed by adding `/` to the path. The picker includes `..` for the parent directory and displays at most four rows. The selected path is added to your message as text; Hobees does not automatically read or attach the file contents. The welcome panel also reports the effective approval level and the tier it came from, so you can see before the first gated tool call whether a tool will prompt, run without asking, be rejected, or pause the run.

### Prompt States

| Prompt                    | Meaning                                       |
| ------------------------- | --------------------------------------------- |
| `🍯 hobees > `            | Default assistant chat and slash-command mode |
| `🍯 (hobees:dev-team) > ` | Locked to Hive "dev-team"                     |

### Slash Commands

| Command                                                                                                                                        | Description                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/provider add \| list \| test \| remove \| models <alias> [--refresh] \| use <alias\|number>`                                                 | Manage LLM providers. `models` only **lists** the models a provider exposes; `use` **switches** the session to that provider                                                                                                                                                                                                                       |
| `/assistant show \| use <provider> [model] \| model [name]`                                                                                    | Configure the default assistant (the agent you chat with). The choice is saved and reused on every launch, so you are not asked again                                                                                                                                                                                                              |
| `/bee create \| list \| update \| delete \| thinking <name> <level>`                                                                           | Manage Worker Bees                                                                                                                                                                                                                                                                                                                                 |
| `/hive create \| add-bee \| remove-bee \| list \| remove \| use <name> \| auto \| thinking <name> <level> \| artifacts [name] \| trace [name]` | Manage Working Hives. `/hive remove` lets you select multiple hives by list number                                                                                                                                                                                                                                                                 |
| `/chat bee <name> \| hive <name> \| list`                                                                                                      | Direct chat with Bee or Hive                                                                                                                                                                                                                                                                                                                       |
| `/goal <goal>`                                                                                                                                 | Run a goal by creating a dynamic Hive; does not reuse a static Hive                                                                                                                                                                                                                                                                                |
| `/usage [all\|bee\|hive\|provider\|day] [--window 1h\|24h\|7d\|all]`                                                                           | Query usage telemetry                                                                                                                                                                                                                                                                                                                              |
| `/thinking <off\|low\|medium\|high\|auto>`                                                                                                     | Session-wide thinking level override                                                                                                                                                                                                                                                                                                               |
| `/approvals [show\|set <level>\|global <level>\|default]` (alias `/permissions`)                                                               | Tool approval level. Plain form sets it for this session; `global <level>` persists it to `~/.hobees/.env`; `default`/`clear` removes the setting for the addressed scope. Shows the effective level, where it comes from, and the level legend. Headless equivalent: `hobees approvals --help` (levels: `interactive`, `auto`, `strict`, `pause`) |
| `/compact`                                                                                                                                     | Compress active thread's message history                                                                                                                                                                                                                                                                                                           |
| `/memory list\|add\|forget\|show [--namespace global\|hive:<name>\|bee:<name>]`                                                                | Cross-session scoped memory                                                                                                                                                                                                                                                                                                                        |
| `/skill list\|show\|create\|save-last\|assign\|unassign\|sync`                                                                                 | Progressive skill library                                                                                                                                                                                                                                                                                                                          |
| `/session save\|load\|list\|delete <name>`                                                                                                     | Named session management                                                                                                                                                                                                                                                                                                                           |
| `/help`                                                                                                                                        | Show all commands                                                                                                                                                                                                                                                                                                                                  |
| `/quit` or `/exit`                                                                                                                             | Exit shell                                                                                                                                                                                                                                                                                                                                         |

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

# Zero-config onboarding: scaffold a built-in template
hobees init --list-templates
hobees init --template code-review               # writes hobees.yaml and imports it
hobees init --template local-ollama              # zero API keys — uses Ollama
hobees init --template research --output r.yaml  # custom output path
hobees init --template code-review --force       # overwrite existing hobees.yaml

# Rerun provider detection at any time
hobees detect-providers
# In the interactive shell:
# /detect_providers

# Declarative setup and direct interactive hive launch
hobees init --config ./hobees.yaml
HOBEES_CONFIG_PATH=./hobees.yaml hobees hive list
hobees shell --hive research-team

# Approval levels — global default, per-session, and per-run
hobees approvals                     # show the effective level and where it comes from
hobees approvals show                # same, explicit form
hobees approvals set auto            # persist a global default in ~/.hobees/.env
hobees approvals clear               # drop back to the context default
hobees approvals --session pause     # this run only, nothing saved
hobees permissions --json            # alias spelling, parseable for CI
hobees approvals --help              # levels, usage and precedence explained
hobees --approval-mode strict        # level for one interactive shell/TUI session
hobees run --hive research-team "Audit the repo" --approval-mode pause
hobees run --hive research-team "Audit the repo" --auto-approve

# Container-aware threads, trace inspection and checkpoint replay
hobees hive run dev-team "Review src/" --thread pr-42 --json     # JSON includes container + thread
HOBEES_CONTAINER_NAME=worker-2 hobees hive run dev-team "Review src/" --thread pr-42 --json
hobees trace --list --limit 20
hobees trace --thread worker-1:hive:dev-team:pr-42
hobees trace --thread pr-42 --container worker-1 --json
hobees hive run dev-team "continue" --thread pr-42 --container worker-1 --resume-decision approve --json
hobees hive run dev-team "retry from that gate" --thread pr-42 --replay 1ef8a9c2-... --patch-message "only run login tests"

# Memory management
hobees memory list --namespace global
hobees memory add user_prefers_typescript "User prefers TypeScript over JavaScript" --namespace global
hobees memory show user_prefers_typescript --namespace global

# Skill management
hobees skill list
hobees skill create --name rust-async-patterns --description "Research Rust async patterns" --from-file ./skill.md
hobees skill assign rust-async-patterns researcher

# Import with collisions handled explicitly (an import writes by name)
hobees import ./hobees.yaml                      # updates entries that already exist
hobees import ./hobees.yaml --on-conflict skip   # keeps existing entries as they are
hobees import ./hobees.yaml --dry-run            # lists what exists before anything is written

# Single-shot execution
hobees -p "summarize the latest docs"

# Local API server
hobees serve --port 8420

# Web UI (Workbench, Studio & Trace Explorer) — default port 6543
hobees web                       # http://127.0.0.1:6543
hobees web --open --read-only    # same port, mutating endpoints disabled

# Usage summary
hobees stats --window 24h --group-by hive

# Clean the slate (headless CLI only; the interactive shell and TUI do not offer it)
hobees reset                     # env file, databases and config files inside ~/.hobees
hobees reset --all               # same, plus artifacts, skills and the scratchpad cache
```

### Reset the slate

`hobees reset` starts hobees over. It lists what exists and asks for a `Y (yes)`
answer before deleting anything — any other answer, or no answer at all, cancels
and nothing is removed. It is headless-only: the interactive shell and the TUI do
not carry a reset command, and the Web UI exposes the same two scopes on the
Studio **Quick setup** tab ([Web App](#-web-app)), where the action stays disabled in
`--read-only` mode and the endpoint only accepts requests from the origin it serves.

| Scope              | What is removed                                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `hobees reset`     | `~/.hobees/.env`, `~/.hobees/.detected`, the SQLite database files (and sidecars) inside `~/.hobees`, `~/.hobees/sessions/` |
| `hobees reset --all` | the above, plus `~/.hobees/artifacts`, `~/.hobees/scratchpad`, the skills library and `HOBEES_ARTIFACTS_ROOT` |

Nothing outside those paths is touched: environment variables exported in your
shell keep their values, a project `.env` you created yourself is left alone, and a
database served outside `~/.hobees` (e.g. PostgreSQL) loses only the URL stored in
the env file — its rows stay on the server.

The database file is always on the plan: when `HOBEES_DATABASE_URL` is not configured
(for example right after a previous reset), `~/.hobees/hobees.db` is taken as the target
through the default path, not skipped. A running process can still hold that file open —
Windows refuses to delete a file with an active handle — so `apply_plan()` releases the
SQLAlchemy pool before deleting, which is why the Studio panel and a reset run by its own
process succeed. If a *different* process (a running web app, an open shell, a
second terminal) holds it, reset does not force anything: it reports that path as failed
and tells you to close that process and run again.

After a reset the next launch rebuilds the slate: provider detection runs again, the
default env file and database are recreated, and `hobees init` ensures the schema. A
running web app needs a restart so the env file and schema are rebuilt too.

## 🖥 Web App

```bash
hobees web                      # http://127.0.0.1:6543 (default port)
hobees web --open --read-only   # mutating endpoints disabled
```

One FastAPI process serves the bundled SPA (no Node runtime) and `/api/v1`.

| View | What it is for |
| --- | --- |
| **Workbench** | provider/model/target pickers, run a goal, live activity feed over SSE; a gate that opens on the watched run shows Approve / Edit / Reject inline |
| **Studio** | **Quick setup** (templates + Reset), Hives, Bees, Providers, Skills, Containers; visual editor or a `hobees.yaml` round-trip |
| **Runs & Traces** | container-keyed thread list, trace detail, checkpoint replay |
| **Memory & Artifacts** | scoped memory browsing, artifacts and download |
| **Approvals (HITL)** | pending gates from `GET /api/v1/approvals`, resolved with `POST /api/v1/approvals/{id}/resolve` or the Workbench card / drawer — same levels, precedence and audit trail as `hobees approvals` and the shell `/approvals` |

Studio extras:

- **Quick setup** — templates on top, **Reset** below (Reset appears only on this tab). Opening Studio without `?tab=` lands there while nothing is configured, otherwise on Hives. A template lists what it creates and every name it collides with; `Skip existing` is the default, and a colliding template needs a typed `Y (yes)` before `POST /api/v1/templates/apply` runs. `GET /api/v1/templates` reports the plan and collisions.
- **Detect providers** (Providers tab) — scans env keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`) and probes `11434` (Ollama), `8080` (llama-server), `1234` (LM Studio); you then register only the candidates you tick. Detection itself writes nothing.
- **Containers** — the tab generates the whole deployable set from what you are happy with now:
  `compose.yaml`, `Dockerfile`, `hobees.yaml` (the active configuration), `goal.txt` and
  `docker-entrypoint.sh`. The `Dockerfile` follows the repo one — `uv tool install hobees` from
  PyPI, no source tree in the image — and the entrypoint initializes the schema with the copied
  config, then runs the goal. The goal reaches the container as a **read-only mount** (default, so
  the goal can change per run without a rebuild), a **baked `COPY`** (opt-in), or **stdin**, and the
  prompt text is never written into the script, so it can never be read as shell. Running the web
  app inside the container is optional and stays commented out by default. Generated paths are
  relative (`./artifacts`, `./skills`, `./goal.txt`) and the container name is read at run time,
  so nothing from one machine is baked into a committed file. Env values stay `${NAME}` references.
  There is no `CMD` in the generated `Dockerfile`: the entrypoint script is the single place that
  decides (init, then the goal), so a baked command line would duplicate it. The tab **only writes
  files** — nothing in it starts or stops a container, so the shown `docker compose run …` command is
  for you or CI to execute. A field change reaches the files only when you click **Update spec**, and
  **Download all files** gives each file as its own download (not a pack).

Read-only mode blocks every mutating call, destructive actions require a typed `Y (yes)`, and reset accepts requests from the origin it serves. `hobees reset` from a terminal is the same two scopes (`~/.hobees` config + `--all` for generated output).

---

## 🧵 Container-Aware Thread IDs & Trace Inspection

Every run is stored under a four-segment thread key, so identical configurations running in different containers against a shared database cannot collide:

```text
<container_name>:<scope>:<entity_name>:<thread_id>
coder-worker-1:hive:dev-team:pr-42
```

| Segment          | Value                                                                                    |
| ---------------- | ---------------------------------------------------------------------------------------- |
| `container_name` | resolved instance identity (see below)                                                   |
| `scope`          | `hive` \| `bee` \| `assistant`                                                           |
| `entity_name`    | hive or bee name, or `default` for the assistant                                         |
| `thread_id`      | your `--thread` value, or an auto-generated 8-char hex run id when `--thread` is omitted |

`container_name` is resolved in order: `--container <name>` → `HOBEES_CONTAINER_NAME` → `HOSTNAME` → `socket.gethostname()` → `local` (Docker sets `HOSTNAME` to the container's 12-char id). Two containers running the same config with `HOBEES_CONTAINER_NAME=worker-1` and `worker-2` and the same `--thread pr-42` produce `worker-1:hive:dev-team:pr-42` and `worker-2:hive:dev-team:pr-42` — no collisions.

- A thread that is already fully qualified is preserved verbatim, so a key copied from `--json` output or from `hobees trace` can be handed straight back as `--thread` (with `--container` to target another instance).
- `hobees hive run --json` reports both `container` and `thread` (the resolved key), plus `pending_approvals` when a gate is still open.
- Thread-key columns accept the full namespaced value: `runs.thread_id`, `usage_events.thread_id`, `memories.source_thread_id` and `skills.source_thread_id` are `VARCHAR(512)`; `runs` and `usage_events` also store `container_name`, and `usage_events` stores `checkpoint_id` per LLM step.

### Trace inspection

`hobees trace` merges the database records with the per-thread JSONL event log:

```bash
hobees trace --list [--container <name>] [--hive <name>] [--limit 20]
hobees trace --thread <id> [--container <name>] [--hive <name>] [--json]
```

The JSON record contains `container`, `thread`, `status` (`completed`, `awaiting_approval`, `failed`, or `unknown` when no run row exists), the `events` read from the JSONL file, `approvals` (mode, decision, `wait_ms`, original vs. edited args, reason) and `usage` (model, latency, tokens, `checkpoint_id`). The human output prints each gate as `GATE <mode>: <tool> [<decision>] bee=<bee>` and then the event list.

Trace events are appended under `artifacts/<hive>/traces/`, and `/hive trace [name]` in the shell or TUI prints the newest log for a hive. Because `:` cannot appear in a Windows filename, the file name escapes it (`:` → `__`) — `coder-worker-1__hive__dev-team__pr-42.jsonl` — while the full key stays inside every event, so reconstruction joins by the event's `thread_id` rather than by the file name. The same escaping is applied to the scratchpad directory that stores offloaded tool output (`artifacts/<hive>/scratchpad/<escaped thread key>/<call_id>.txt`), so the path a Bee is shown is the path it can actually read back.

### Replay from a checkpoint

```bash
hobees hive run dev-team "retry from that gate" --thread pr-42 --replay <checkpoint_id>
hobees hive run dev-team "..." --thread pr-42 --replay <checkpoint_id> --patch-message "only run login tests"
```

The checkpoint must exist in the resolved thread's state history — the run fails fast with a clear error if it does not. `--patch-message` appends a human message to that snapshot before forking forward, so only the steps after the checkpoint re-run, using the Bee prompts and models as they are configured now.

### Not built yet on this branch

- Structured log enrichment (per-line `container` / `thread` / `checkpoint_id` context and `--log-format json` / `HOBEES_LOG_FORMAT`) is specified in `specs/Trace.md` but not implemented; trace visibility comes from the JSONL event log and the database.
- The TUI trace tree and its inspector pane with `[r] Replay` are not implemented — `hobees trace` prints a flat list and its `checkpoints` field is reserved (currently empty).
- Shell/TUI chat turns honour `auto` and `strict` immediately, but the Approve/Edit/Reject prompt loop only exists in `hobees hive run`; single-Bee chat turns also record the container segment as `local` instead of the resolved name.

---

## Configuration

Application settings are loaded from `~/.hobees/.env` (or local `.env`) with the `HOBEES_` prefix. PostgreSQL is recommended for multi-process use; SQLite is also supported for local/single-user use.

### Database and startup configuration

| Variable                | Description                                                                                          |
| ----------------------- | ---------------------------------------------------------------------------------------------------- |
| `HOBEES_DATABASE_URL`   | Database URL, e.g. `postgresql+psycopg://user:pass@localhost:5432/hobees` or `sqlite:///./hobees.db` |
| `HOBEES_CONFIG_PATH`    | Optional YAML/JSON config file to synchronize automatically before normal CLI commands               |
| `HOBEES_ARTIFACTS_ROOT` | Root directory for per-hive run artifacts (default: `./artifacts`)                                   |

### Choosing SQLite or PostgreSQL

Set `HOBEES_DATABASE_URL` in `~/.hobees/.env`, the project `.env`, or the
process environment to select the database for both Hobees application data and
LangGraph checkpoints; there is no interactive database chooser. If no URL is
configured, Hobees writes a platform-specific SQLite URL pointing to
`~/.hobees/hobees.db` into `~/.hobees/.env` and prints the database file
location in the CLI. Both paths use the current user's home directory on Linux,
macOS, and Windows.

The interactive shell initializes a fresh database automatically, so
`hobees init` is not required just to start the shell. Use `hobees init` to
initialize the database explicitly before other database-backed commands, or
to run migrations and configuration import.

For a local, single-user setup, use file-backed SQLite:

```dotenv
# Add to ~/.hobees/.env or the project .env:
HOBEES_DATABASE_URL=sqlite:///./hobees.db
```

Without an explicit URL, Hobees stores the default database under the user's
`.hobees` directory. You can configure another SQLite path or PostgreSQL URL
explicitly.

```bash
uv run hobees init
```

Relative SQLite paths that you configure yourself are resolved from the
working directory where Hobees runs. The default database location is stable
across working directories. File-backed SQLite keeps data and checkpoints
between runs; `sqlite:///:memory:` is temporary and is not suitable for
persistent use.
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

| Variable                       | Default                                     | Description                                                                                                                                                                                                                      |
| ------------------------------ | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `HOBEES_QUEEN_PROVIDER`        | `openai`                                    | Default Queen provider alias                                                                                                                                                                                                     |
| `HOBEES_QUEEN_MODEL`           | `gpt-4o-mini`                               | Default Queen model                                                                                                                                                                                                              |
| `HOBEES_API_HOST`              | `127.0.0.1`                                 | FastAPI bind host                                                                                                                                                                                                                |
| `HOBEES_API_PORT`              | `8420`                                      | FastAPI bind port                                                                                                                                                                                                                |
| `HOBEES_LOG_LEVEL`             | `INFO`                                      | Application log level                                                                                                                                                                                                            |
| `HOBEES_COMPACTION_THRESHOLD`  | `0.65`                                      | Fraction of context window before compaction                                                                                                                                                                                     |
| `HOBEES_MAX_TOOL_OUTPUT_CHARS` | `8000`                                      | Max chars for tool output before scratchpad offload                                                                                                                                                                              |
| `HOBEES_ENABLE_AUTO_MEMORY`    | `false`                                     | After successful Hive runs, make an extra model call to save stable preferences globally and (for named Hives) durable Hive-specific facts                                                                                       |
| `HOBEES_SKILLS_DIR`            | `~/.hobees/skills`                          | Directory for skill Markdown files                                                                                                                                                                                               |
| `HOBEES_TRACE_CONTENT_MODE`    | `summary`                                   | Trace message content: `metadata` (no message text), `summary` (short previews with best-effort secret redaction), or `full` (full messages with best-effort secret redaction). Tool argument and result values are never logged |
| `HOBEES_APPROVAL_MODE`         | _(unset)_                                   | Global tool approval level (`interactive` \| `auto` \| `strict` \| `pause`), written by `hobees approvals set <level>`. When unset the context default applies: `interactive` on a TTY, `strict` in headless runs                |
| `HOBEES_CONTAINER_NAME`        | _(unset → `HOSTNAME` → hostname → `local`)_ | Instance identity used as the first segment of every thread key. Precedence: `--container` → this variable → `HOSTNAME` → `socket.gethostname()` → `local`                                                                       |

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

The generated set runs a goal from a file or a pipe, which is what a pipeline wants:

```bash
# read-only mount (default): change the goal without rebuilding the image
docker compose run --rm --profile pipeline init
printf '%s' "Review src/ for race conditions" | docker compose run -T --rm --profile pipeline hobees run --hive dev-team -
docker compose run --rm --profile pipeline hobees run --hive dev-team --goal-file /data/goal.txt --json

# baked mode: the image is runnable on its own, but the goal is frozen in a layer
docker compose run --rm --profile pipeline hobees   # entrypoint: init, then the goal file
```

### How a pipeline knows the run ended

Nothing has to be added to the `Dockerfile` for this: hobees already exits with a meaningful code, and
that code is the container's exit code. `docker run` and `docker compose run` hand it back to the
caller, and that stays true when the container runs against a remote daemon (`DOCKER_HOST`,
`docker -H ssh://pipeline-host` or `docker -H tcp://host:2376`) - the CLI's own exit status is the
container's, so a CI step can simply test `$?` or `if ! docker compose run ...; then exit 1; fi`.

| Code | Meaning |
| --- | --- |
| 0 | completed |
| 1 | failed (error, timeout, bad config) |
| 2 | stopped for an approval a headless run cannot answer |
| 3 | still running (a status read that has not reached a terminal state) |

The generated `docker-entrypoint.sh` keeps that path intact: `set -eu` stops on the first failure with
that command's code, and `exec` replaces the shell so hobees' exit code is reported unchanged.

A detached run has to read the code back:

```bash
docker compose run --rm --profile pipeline hobees            # exit status == the container's
docker compose up -d --profile pipeline                      # detached: inspect afterwards
docker inspect -f "{{.State.ExitCode}}" <container>
docker compose up --exit-code-from hobees --profile pipeline # compose exits with the service's code
```

`hobees pipeline status` is the richer reading of the same outcome. It reads the manifest the run wrote
into the artifacts mount, or the run row, prints status/error, and exits with the matching code - which
is what a pipeline manager wants when the container ran on another host and only the mounted artifacts
come back:

```bash
hobees pipeline status --hive dev-team --json                  # status, error, exit_code, thread
hobees pipeline status --hive dev-team --poll 5 --timeout 120  # wait for a terminal state
hobees pipeline status --thread-id 91318583
```

Every manifest entry now carries `exit_code`, so the two signals cannot disagree: the shell sees the
number, and the JSON says the same number with the reason attached.
The run writes the manifest to its artifacts directory and the run row to the database, so a pipeline
manager on a different host has three ways to learn the outcome: the exit code from the `docker` call
(it propagates over a remote daemon), the manifest through a shared mount, or the database row - the
last two are what `hobees pipeline status` reads. Point `--manifest` at the shared path, or use
`--hive`/`--thread-id` when the pipeline shares the same PostgreSQL.


The `./artifacts` bind mount makes run outputs available on the host (worker-created files are under `artifacts/<hive>/output/`), and `./skills` persists Markdown skill files. The named `postgres_data` volume preserves providers, Bees, Hives, runs, memories, and checkpoints across container recreation and `docker compose down`. Remove the corresponding volume mappings from `compose.yaml` if persistence is not wanted. **`docker compose down -v` deletes the database volume and its contents.**

A one-shot container is headless, so the approval default there is `strict`: a gated tool does not run unless the container sets `HOBEES_APPROVAL_MODE=auto` (or `pause`) in `.env` or passes `--approval-mode`. Container identity is `HOBEES_CONTAINER_NAME` if set, otherwise `HOSTNAME` (Docker's 12-char container id), so parallel workers using the same `hobees.yaml` write distinct thread keys — `worker-1:hive:...` vs `worker-2:hive:...` — and each run can be inspected from any other container with `hobees trace --container <name> --thread <id>`.

To load declarative setup, uncomment the optional `./config:/config:ro` mount in `compose.yaml`, set `HOBEES_CONFIG_PATH=/config/hobees.yaml` in `.env`, and place the config file in `./config`. You can instead run a one-time import with `docker compose run --rm hobees init --config /config/hobees.yaml`.

The web UI's **Studio → Containers** tab prepares that deployment from the browser: it builds the
`compose.yaml`, `Dockerfile`, `hobees.yaml`, `goal.txt` and `docker-entrypoint.sh` from the live
settings and the registered providers, shows validation warnings, and can save them to the project
root (`HOBEES_PROJECT_ROOT`, fixed names) or download each file separately. The tab does not start or
stop containers — `docker` and `docker compose` are run by you or by CI. The `Dockerfile` installs
`hobees` from PyPI (`uv tool install hobees`), has no source tree in the image, and defines no `CMD`:
`docker-entrypoint.sh` is what runs, initializing hobees with the copied config and then running the
goal, with arguments passed to `docker compose run` as the override. Generated files reference
environment variables by name (`${OPENAI_API_KEY}`), never by value, and run as a non-root user.

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

| Endpoint                           | Description                                                        |
| ---------------------------------- | ------------------------------------------------------------------ |
| `GET /api/health`                  | Service and database status                                        |
| `GET /api/roster`                  | Providers, Bees, and Hives                                         |
| `GET /api/runs`                    | Run history, optionally filtered by status                         |
| `GET /api/runs/active`             | Active runs                                                        |
| `GET /api/runs/{thread_id}`        | Run details and trace                                              |
| `GET /api/runs/{thread_id}/stream` | SSE trace replay and live updates                                  |
| `GET /api/stats`                   | Aggregated usage (`?group_by=bee\|hive\|provider\|day&window=24h`) |
| `GET /api/stats/recent`            | Recent usage events                                                |
| `GET /api/usage/stream`            | SSE usage events                                                   |

---

## Feature Highlights

### 🔐 Approval Gates & 🧵 Namespaced Threads

See [Approval Gates (HITL)](#-approval-gates-hitl) and [Container-Aware Thread IDs & Trace Inspection](#-container-aware-thread-ids--trace-inspection): per-Bee gated tools, four runtime levels, audited decisions, collision-free container keys, `hobees trace`, and `--replay` / `--resume-decision`.

### 🤖 Provider Model Auto-Discovery

Fetch available models from local (llama.cpp, Ollama, vLLM, LM Studio) or remote (OpenAI, Anthropic, Gemini, OpenRouter) providers.

```bash
/provider models openai-main --refresh
# or during /bee create, /hive create - interactive model picker appears
```

### 💭 Configurable Thinking Levels

Normalized `thinking_level` (`off` | `low` | `medium` | `high`) per Bee, Hive Supervisor, or session override.

| Provider               | `off`                                        | `low`       | `medium`    | `high`       |
| ---------------------- | -------------------------------------------- | ----------- | ----------- | ------------ |
| OpenAI                 | no reasoning_effort                          | `low`       | `medium`    | `high`       |
| Anthropic              | no thinking                                  | 1024 tokens | 4096 tokens | 16384 tokens |
| Google GenAI           | thinking_budget=0                            | 1024        | 8192        | 24576        |
| llama.cpp / OpenRouter | reasoning_effort=none, enable_thinking=false | `low`       | `medium`    | `xhigh`      |

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

| Namespace     | Scope                                         |
| ------------- | --------------------------------------------- |
| `global`      | User preferences, facts across all sessions   |
| `hive:<name>` | Project-specific context shared within a hive |
| `bee:<name>`  | Bee-specific learned patterns                 |

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

Approval-level behaviour is covered by `tests/test_approvals.py` (resolver precedence, persistence, the headless command, the shell/TUI handlers, and the rule that completion suggestions are words the handler accepts). Container-aware thread namespacing, gate decisions and the Windows-safe trace filename are covered by `tests/test_hitl.py`.

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
# Set HOBEES_DATABASE_URL in ~/.hobees/.env and export provider API keys in the process environment.

# Initialize
uv run hobees init
```

### High-Level Project Structure

```text
hobees/
├── src/hobees/       # Application package
│   ├── api/          # FastAPI HTTP and streaming endpoints
│   ├── cli/          # CLI, REPL, and TUI interfaces
│   ├── core/         # Agent orchestration and application services
│   ├── db/           # Database models and persistence
│   └── config.py     # Pydantic settings
├── tests/            # Automated test suite
├── pyproject.toml    # Project and tool configuration
├── uv.lock           # Dependency lockfile
├── Dockerfile        # Container build
└── compose.yaml      # Container orchestration
```

### Adding Custom Tools

1. Add a new `@tool` function in `core/tool_registry.py`
2. Register it in `TOOL_REGISTRY`
3. Bees can now reference it by key in `tool_names`

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
