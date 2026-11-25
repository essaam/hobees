"""``hobees`` / ``hobiz`` Typer entrypoint.

CLI command modules are imported to register commands; database, model, and
API services are loaded lazily by execution handlers. No cold-start timing
target has been measured.
"""

from __future__ import annotations

import sys
import uuid
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from hobees.cli.icons import APP, ERROR, SUCCESS, WARN
from hobees.cli.approval_cmd import approvals_command
from hobees.cli.bee_cmd import app as bee_app
from hobees.cli.hive_cmd import app as hive_app
from hobees.cli.provider_cmd import app as provider_app
from hobees.cli.memory_cmd import app as memory_app
from hobees.cli.pipeline_cmd import app as pipeline_app
from hobees.cli.reset_cmd import reset_command
from hobees.cli.skill_cmd import app as skill_app
from hobees.cli.import_cmd import import_config

app = typer.Typer(
    name="hobees",
    help="🍯 hobees — interactive CLI multi-agent orchestrator (LangGraph + PostgreSQL)",
    no_args_is_help=False,
    invoke_without_command=True,
)
console = Console()
app.add_typer(provider_app, name="provider")
app.add_typer(bee_app, name="bee")
app.add_typer(hive_app, name="hive")
app.add_typer(memory_app, name="memory")
app.add_typer(skill_app, name="skill")
app.add_typer(pipeline_app, name="pipeline")
# `/approvals` on the interactive side, `hobees approvals` headless; `permissions`
# is accepted as an alias of both.
app.command(name="approvals")(approvals_command)
app.command(name="permissions")(approvals_command)
app.command(name="import")(import_config)
# `hobees reset` is headless only: the interactive shell and the TUI do not offer
# a command that deletes the slate, so it stays out of the slash-command catalog.
app.command(name="reset")(reset_command)


def _approval_session_level(
    level: str | None,
    auto_approve: bool = False,
) -> str | None:
    """Validate a per-session `--approval-mode` value (no persistence)."""
    from hobees.cli.approval_cmd import normalize_level

    if auto_approve:
        return "auto"
    if level is None:
        return None
    normalized = normalize_level(level)
    if normalized is None:
        from hobees.core.approval import APPROVAL_MODES

        console.print(
            f"{ERROR} Invalid approval level: {level}. "
            f"Choose {', '.join(APPROVAL_MODES)}."
        )
        raise typer.Exit(code=1)
    return normalized


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        console.print(f"hobees {version('hobees')}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v", help="Show version and exit", callback=_version_callback
    ),
    session: str | None = typer.Option(
        None, "--session", "-s", help="Resume a named session by name"
    ),
    new_session: str | None = typer.Option(
        None, "--new-session", "-n", help="Start a new named session"
    ),
    tui: bool = typer.Option(
        False, "--tui", help="Use experimental TUI instead of legacy shell"
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="Provider alias to use as default for this session"
    ),
    model: str | None = typer.Option(
        None, "--model", help="Model name to use for this session"
    ),
    hive: str | None = typer.Option(
        None, "--hive", help="Hive to launch directly into for this session"
    ),
    approval_mode: str | None = typer.Option(
        None,
        "--approval-mode",
        help="Approval level for this session: interactive|auto|strict|pause",
    ),
    auto_approve: bool = typer.Option(
        False, "--auto-approve", help="Convenience alias for --approval-mode auto"
    ),
) -> None:
    """hobees — run with no arguments to enter the interactive shell."""
    if not ctx.resilient_parsing:
        from hobees.config import ensure_database_url, get_default_database_path, settings

        # `reset` must not re-create the env file and database it is about to remove.
        if ctx.invoked_subcommand != "reset" and ensure_database_url():
            database_path = escape(str(get_default_database_path()))
            console.print(
                f"{WARN} HOBEES_DATABASE_URL is not set; using local SQLite "
                f"database at {database_path}. "
                "Set HOBEES_DATABASE_URL to use another database."
            )

        if ctx.invoked_subcommand not in ("init", "import", "reset") and settings.config_path:
            _sync_startup_config(settings.config_path)

    # If no subcommand was invoked, run the shell
    if ctx.invoked_subcommand is None:
        # Pass session info to shell
        ctx.obj = {
            "resume_session": session,
            "new_session_name": new_session,
            "default_provider": provider,
            "default_model": model,
            "active_hive": hive,
            "approval_mode": _approval_session_level(approval_mode, auto_approve),
        }
        from hobees.db.session import get_engine, session_scope
        from hobees.db.models import LLMProvider

        engine = get_engine()
        _ensure_database_initialized(engine)
        with session_scope() as session:
            providers = session.query(LLMProvider).all()
            db_url = engine.url

        # First-launch detection is one-time; users can rerun it explicitly later.
        if _run_provider_detection_if_needed(providers):
            # Re-query after potential registration
            with session_scope() as session:
                providers = session.query(LLMProvider).all()

        selected_provider = None
        if provider:
            # User specified a provider via --provider
            selected_provider = next((p for p in providers if p.alias == provider), None)
            if not selected_provider:
                console.print(f"{ERROR} Provider '{provider}' not found.")
                raise typer.Exit(code=1)
        elif len(providers) == 1:
            # Only one provider - use it as default
            selected_provider = providers[0]
        elif len(providers) > 1:
            # Multiple providers - will prompt user in shell
            pass
            
        if tui:
            from hobees.cli.tui import run_tui
            run_tui(selected_provider, db_url, ctx.obj)
        else:
            from hobees.cli.shell import _shell_loop
            _shell_loop(ctx.obj, selected_provider)


def _migrate_json_column(
    engine,
    table_name: str,
    column_name: str,
    default: str | None = None,
) -> None:
    """Convert legacy PostgreSQL text columns to the ORM's JSON type."""
    from sqlalchemy import JSON, inspect, text

    if engine.dialect.name != "postgresql":
        return

    column = next(
        column
        for column in inspect(engine).get_columns(table_name)
        if column["name"] == column_name
    )
    if isinstance(column["type"], JSON):
        return

    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP DEFAULT")
        )
        connection.execute(
            text(
                f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
                f"TYPE JSON USING {column_name}::json"
            )
        )
        if default is not None:
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
                    f"SET DEFAULT '{default}'::json"
                )
            )


def _run_migrations(engine) -> None:
    """Run schema migrations for existing databases."""
    from sqlalchemy import JSON, inspect, text

    inspector = inspect(engine)
    json_type = JSON().compile(dialect=engine.dialect)
    
    # Check and add missing columns to llm_providers
    if "llm_providers" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("llm_providers")]
        with engine.connect() as conn:
            if "context_window_tokens" not in columns:
                conn.execute(text("ALTER TABLE llm_providers ADD COLUMN context_window_tokens INTEGER DEFAULT 128000"))
                console.print(f"{SUCCESS} Added column: llm_providers.context_window_tokens")
            if "available_models" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE llm_providers "
                        f"ADD COLUMN available_models {json_type} DEFAULT '[]'"
                    )
                )
                console.print(f"{SUCCESS} Added column: llm_providers.available_models")
            if "models_refreshed_at" not in columns:
                conn.execute(text("ALTER TABLE llm_providers ADD COLUMN models_refreshed_at TIMESTAMP"))
                console.print(f"{SUCCESS} Added column: llm_providers.models_refreshed_at")
            conn.commit()
        _migrate_json_column(engine, "llm_providers", "available_models", "[]")
    
    # Check and add thinking_level to bees
    if "bees" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("bees")]
        with engine.connect() as conn:
            if "thinking_level" not in columns:
                conn.execute(text("ALTER TABLE bees ADD COLUMN thinking_level VARCHAR(16) DEFAULT 'off'"))
                console.print(f"{SUCCESS} Added column: bees.thinking_level")
            if "require_approval" not in columns:
                conn.execute(text("ALTER TABLE bees ADD COLUMN require_approval JSON DEFAULT '[]'"))
                console.print(f"{SUCCESS} Added column: bees.require_approval")
            conn.commit()
    
    # Check and add supervisor_thinking_level to hives
    if "hives" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("hives")]
        with engine.connect() as conn:
            if "supervisor_thinking_level" not in columns:
                conn.execute(text("ALTER TABLE hives ADD COLUMN supervisor_thinking_level VARCHAR(16) DEFAULT 'medium'"))
                console.print(f"{SUCCESS} Added column: hives.supervisor_thinking_level")
            if "project_path" not in columns:
                conn.execute(text("ALTER TABLE hives ADD COLUMN project_path VARCHAR(512)"))
                console.print(f"{SUCCESS} Added column: hives.project_path")
            conn.commit()
    
    # Check and add compacted_count and suggested_skill_draft to runs
    if "runs" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("runs")]
        with engine.connect() as conn:
            if "container_name" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN container_name VARCHAR(128)"))
            if "compacted_count" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN compacted_count INTEGER DEFAULT 0"))
                console.print(f"{SUCCESS} Added column: runs.compacted_count")
            if "suggested_skill_draft" not in columns:
                conn.execute(
                    text(
                        f"ALTER TABLE runs ADD COLUMN suggested_skill_draft {json_type}"
                    )
                )
                console.print(f"{SUCCESS} Added column: runs.suggested_skill_draft")
            if "artifacts_dir" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN artifacts_dir VARCHAR(1024)"))
                console.print(f"{SUCCESS} Added column: runs.artifacts_dir")
            conn.commit()
        _migrate_json_column(engine, "runs", "suggested_skill_draft")

    # Trace observability enrichment
    if "usage_events" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("usage_events")]
        with engine.connect() as conn:
            if "container_name" not in columns:
                conn.execute(text("ALTER TABLE usage_events ADD COLUMN container_name VARCHAR(128)"))
            if "checkpoint_id" not in columns:
                conn.execute(text("ALTER TABLE usage_events ADD COLUMN checkpoint_id VARCHAR(128)"))
            conn.commit()
    
    # Create new tables if they don't exist (memories, skills, bee_skills)
    # These will be created by Base.metadata.create_all() anyway


def _run_provider_detection() -> None:
    """Scan env + local ports, then offer to register detected providers.

    After running (whether or not any providers are found), the sentinel file
    ``~/.hobees/.detected`` records that automatic first-launch detection ran.
    This function is also used by the explicit CLI and shell commands.
    """
    from rich.prompt import Confirm
    from rich.table import Table as RichTable

    from hobees.core.provider_detector import (
        auto_register_providers,
        detect_available_providers,
        get_registered_provider_aliases,
        mark_detected,
    )

    console.print(f"\n{APP} Scanning your environment for available providers...\n")

    candidates = detect_available_providers()

    if not candidates:
        console.print(f"{WARN} No providers detected automatically.")
        console.print(
            "  To get started:\n"
            "    • Cloud: set OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY, then rerun.\n"
            "    • Local (free): install [link=https://ollama.com]Ollama[/link] or llama-server, then rerun.\n"
            f"    • Manual: run [bold]hobees provider add[/bold]\n"
            f"    • Template: run [bold]hobees init --template local-ollama[/bold]\n"
        )
        mark_detected()
        return

    registered_aliases = get_registered_provider_aliases()
    already_registered = [c for c in candidates if c["alias"] in registered_aliases]
    candidates = [c for c in candidates if c["alias"] not in registered_aliases]

    if already_registered:
        aliases = ", ".join(c["alias"] for c in already_registered)
        console.print(f"{WARN} Already registered; skipping: {aliases}")

    if not candidates:
        console.print(f"{SUCCESS} All detected providers are already registered. No changes made.")
        mark_detected()
        return

    tbl = RichTable(title="Detected Providers", show_lines=False)
    tbl.add_column("Alias", style="cyan", no_wrap=True)
    tbl.add_column("Type")
    tbl.add_column("Source", style="dim")
    for c in candidates:
        tbl.add_row(c["alias"], c["provider_type"], c.get("source_label", ""))
    console.print(tbl)

    # In non-interactive (CI) mode, skip the prompt and auto-register
    is_interactive = sys.stdin.isatty()
    do_register = True
    if is_interactive:
        do_register = Confirm.ask("\nRegister these providers now?", default=True)

    if do_register:
        registered = auto_register_providers(candidates)
        if registered:
            console.print(f"\n{SUCCESS} Registered: {', '.join(registered)}")
            console.print(
                f"\n{APP} [dim]Tip: scaffold a hive with "
                f"[bold]hobees init --template code-review[/bold][/dim]"
            )
        else:
            console.print(f"{WARN} No new providers registered (all already exist).")
    else:
        console.print("Skipped. Run [bold]hobees provider add[/bold] to add providers manually.")

    mark_detected()


def _run_provider_detection_if_needed(providers: Sequence[object]) -> bool:
    """Run automatic detection on an empty registry, once per user profile."""
    if providers:
        return False

    from hobees.core.provider_detector import is_first_launch

    if not is_first_launch():
        return False

    _run_provider_detection()
    return True


@app.command(name="detect-providers")
def detect_providers() -> None:
    """Detect available cloud and local providers, then register them."""
    from hobees.db.session import get_engine

    _ensure_database_initialized(get_engine())
    _run_provider_detection()


def _ensure_database_initialized(engine) -> None:
    """Create the initial schema when the database has not been initialized."""
    from sqlalchemy import inspect

    if "llm_providers" in inspect(engine).get_table_names():
        return

    from hobees.db.models import Base

    Base.metadata.create_all(engine)
    _run_migrations(engine)
    _setup_postgres_checkpointer(engine.url)
    console.print(f"{SUCCESS} Database schema initialized.")


def _sync_startup_config(config_path: Path) -> None:
    """Create the schema and reconcile the configured resources before a command runs."""
    from hobees.db.session import get_engine
    from hobees.db.models import Base

    if not config_path.is_file():
        console.print(f"{ERROR} Config path {config_path} does not exist or is not a file.")
        raise typer.Exit(code=1)
    try:
        engine = get_engine()
        Base.metadata.create_all(engine)
        _run_migrations(engine)
        _setup_postgres_checkpointer(engine.url)
        from hobees.cli.import_cmd import import_config

        import_config(config_path, dry_run=False, force=True)
    except Exception as exc:
        console.print(f"{ERROR} Failed to synchronize config {config_path}: {exc}")
        raise typer.Exit(code=1) from exc


def _setup_postgres_checkpointer(db_url) -> None:
    from hobees.db.backends import get_database_backend, get_postgres_checkpoint_url

    if get_database_backend(db_url) == "sqlite":
        return
    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        conn_string = get_postgres_checkpoint_url(db_url)
        with PostgresSaver.from_conn_string(conn_string) as saver:
            saver.setup()
        console.print(f"{SUCCESS} LangGraph PostgresSaver checkpoint tables ensured.")
    except ImportError:
        console.print(
            f"{WARN} langgraph-checkpoint-postgres not installed; skipping checkpoint tables."
        )
    except Exception as exc:  # pragma: no cover - depends on live Postgres
        console.print(f"{ERROR} PostgresSaver.setup() failed: {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def init(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to config file (YAML/JSON) to import after initialization"),
    ] = None,
    template: Annotated[
        str | None,
        typer.Option(
            "--template", "-t",
            help="Scaffold from a built-in template: code-review, research, docs-writer, local-ollama, local-llamacpp",
        ),
    ] = None,
    list_templates: Annotated[
        bool,
        typer.Option("--list-templates", help="List all available built-in templates and exit"),
    ] = False,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Destination path for the scaffolded config (default: hobees.yaml)"),
    ] = Path("hobees.yaml"),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite destination file if it already exists"),
    ] = False,
) -> None:
    """Create database tables and optionally scaffold or auto-import config.

    Creates the SQLAlchemy schema and initializes PostgreSQL checkpoints when
    applicable. If HOBEES_DATABASE_URL is not configured, local SQLite is
    selected automatically. PostgreSQL is recommended for multi-process use;
    SQLite is supported for local use. Also runs migrations for existing
    databases and imports config if specified.

    With ``--template``, copies a built-in starter blueprint to disk and
    immediately imports it so you can start using hobees in one command.

    Examples::

        hobees init --template code-review
        hobees init --template local-ollama --output my-local.yaml
        hobees init --list-templates
        hobees init --config path/to/existing.yaml
    """
    from hobees.db.session import get_engine
    from hobees.db.models import Base

    # --list-templates: show catalogue and exit before touching the DB
    if list_templates:
        from hobees.templates import AVAILABLE_TEMPLATES
        from rich.table import Table as RichTable

        tbl = RichTable(title="Built-in hobees Templates", show_lines=False)
        tbl.add_column("Name", style="cyan", no_wrap=True)
        tbl.add_column("Description")
        for name, desc in AVAILABLE_TEMPLATES.items():
            tbl.add_row(name, desc)
        console.print(tbl)
        console.print(f"\n  Usage: [bold]hobees init --template <name>[/bold]")
        return

    # --template and --config are mutually exclusive
    if template and config:
        console.print(f"{ERROR} --template and --config are mutually exclusive. Use one at a time.")
        raise typer.Exit(code=1)

    # --template: scaffold a built-in blueprint
    if template:
        from hobees.templates import AVAILABLE_TEMPLATES, get_template_text

        if template not in AVAILABLE_TEMPLATES:
            valid = ", ".join(AVAILABLE_TEMPLATES)
            console.print(f"{ERROR} Unknown template {template!r}. Valid options: {valid}")
            console.print(f"  Run [bold]hobees init --list-templates[/bold] to see all options.")
            raise typer.Exit(code=1)

        dest = Path(output)
        if dest.exists() and not force:
            console.print(
                f"{ERROR} {dest} already exists. Use --force to overwrite, "
                f"or --output to choose a different destination."
            )
            raise typer.Exit(code=1)

        try:
            yaml_text = get_template_text(template)
        except (KeyError, FileNotFoundError) as exc:
            console.print(f"{ERROR} Could not load template {template!r}: {exc}")
            raise typer.Exit(code=1) from exc

        dest.write_text(yaml_text, encoding="utf-8")
        console.print(f"{SUCCESS} Scaffolded template [bold]{template}[/bold] → {dest}")
        # Use the scaffolded file as the config to import
        config = dest

    engine = get_engine()
    try:
        Base.metadata.create_all(engine)
        console.print(f"{SUCCESS} SQLAlchemy tables ensured.")
    except Exception as exc:  # pragma: no cover - depends on live Postgres
        console.print(f"{ERROR} Failed to create SQLAlchemy tables: {exc}")
        raise typer.Exit(code=1)
    
    # Run migrations for existing databases
    _run_migrations(engine)

    # Only run PostgresSaver.setup() for PostgreSQL, not SQLite
    from hobees.db.backends import get_database_backend

    if get_database_backend(engine.url) == "sqlite":
        console.print(
            f"{WARN} PostgreSQL checkpoint setup skipped; SQLite checkpoints initialize when used."
        )
    else:
        _setup_postgres_checkpointer(engine.url)

    # Auto-import config if provided or HOBEES_CONFIG_PATH is set
    from hobees.config import settings
    cfg_file = config or settings.config_path
    if cfg_file:
        cfg_path = Path(cfg_file)
        if cfg_path.exists():
            console.print(f"\n{APP} [bold]Auto-importing declarative config from {cfg_path}...[/bold]")
            from hobees.cli.import_cmd import import_config
            import_config(cfg_path, dry_run=False, force=True)
        else:
            console.print(f"{WARN} Config path {cfg_path} not found.")


@app.command()
def trace(
    thread: str | None = typer.Option(None, "--thread", "-t", help="Thread ID or short thread suffix"),
    container: str | None = typer.Option(None, "--container", "-c", help="Container/instance name"),
    hive: str | None = typer.Option(None, "--hive", help="Hive entity name"),
    list_threads: bool = typer.Option(False, "--list", help="List recent threads"),
    limit: int = typer.Option(20, "--limit", help="Maximum threads to list"),
    output_json: bool = typer.Option(False, "--json", help="Emit structured JSON"),
) -> None:
    """Inspect namespaced runs and approval gates."""
    from hobees.core.approval import resolve_container_name, resolve_thread_id
    from hobees.core.tracing import trace_filename
    from hobees.db.models import ApprovalEvent, Run, UsageEvent
    from hobees.db.session import session_scope

    container = resolve_container_name(container)

    with session_scope() as session:
        if list_threads:
            query = session.query(Run)
            if container:
                query = query.filter(
                    (Run.container_name == container) | (Run.container_name.is_(None))
                )
            if hive:
                from hobees.db.models import Hive
                hive_row = session.query(Hive).filter_by(name=hive).first()
                if hive_row:
                    query = query.filter(Run.hive_id == hive_row.id)
            runs = query.order_by(Run.started_at.desc()).limit(limit).all()
            rows = [
                {
                    "container": run.container_name or container,
                    "thread": run.thread_id,
                    "status": run.status,
                    "goal": run.goal,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                }
                for run in runs
            ]
            if output_json:
                console.print_json(json.dumps(rows))
            else:
                table = Table(title="Recent Trace Threads")
                table.add_column("Container")
                table.add_column("Thread")
                table.add_column("Status")
                table.add_column("Goal")
                for row in rows:
                    table.add_row(row["container"], row["thread"], row["status"], row["goal"][:80])
                console.print(table)
            return

        if not thread:
            console.print(f"{ERROR} Specify --thread or --list")
            raise typer.Exit(code=1)
        resolved = resolve_thread_id(
            "hive" if hive else "hive",
            hive or "default",
            thread,
            container,
        )

        approvals = session.query(ApprovalEvent).filter_by(thread_id=resolved).all()
        usage = session.query(UsageEvent).filter_by(thread_id=resolved).all()
        run = session.query(Run).filter_by(thread_id=resolved).first()

    trace_events = []
    trace_roots = [Path.cwd() / "artifacts", Path.home() / ".hobees" / "artifacts"]
    expected_name = trace_filename(resolved)
    for root in trace_roots:
        if root.exists():
            for path in root.rglob(expected_name):
                try:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            trace_events.append(json.loads(line))
                except (OSError, json.JSONDecodeError):
                    continue

    approval_rows = []
    for event in approvals:
        wait_ms = None
        if event.resolved_at and event.requested_at:
            wait_ms = int((event.resolved_at - event.requested_at).total_seconds() * 1000)
        approval_rows.append({
            "checkpoint_id": event.checkpoint_id,
            "bee": event.bee_name,
            "tool": event.tool_name,
            "tool_call_id": event.tool_call_id,
            "mode": event.approval_mode,
            "decision": event.decision,
            "wait_ms": wait_ms,
            "original_args": json.loads(event.original_args_json or "{}"),
            "final_args": json.loads(event.final_args_json) if event.final_args_json else None,
            "reason": event.reason,
        })

    usage_rows = [
        {
            "bee": item.bee_name,
            "model": item.model_name,
            "latency_ms": item.latency_ms,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "checkpoint_id": item.checkpoint_id,
        }
        for item in usage
    ]
    result = {
        "container": container,
        "thread": resolved,
        "status": run.status if run else ("awaiting_approval" if approvals and any(a.decision == "pending" for a in approvals) else "unknown"),
        "checkpoints": [],
        "events": trace_events,
        "approvals": approval_rows,
        "usage": usage_rows,
    }
    if output_json:
        console.print_json(json.dumps(result))
    else:
        console.print(f"[bold]Thread:[/bold] {resolved}")
        console.print(f"[bold]Status:[/bold] {result['status']}")
        for approval in approval_rows:
            console.print(
                f"  GATE {approval['mode']}: {approval['tool']} "
                f"[{approval['decision']}] bee={approval['bee']}"
            )
        for event in trace_events:
            console.print(
                f"  [{event.get('event_type')}] "
                f"{event.get('source')}"
                f"{' -> ' + event.get('target') if event.get('target') else ''}"
            )


@app.command()
def stats(
    window: str = typer.Option("all", "--window", "-w", help="Time window: 1h, 24h, 7d, all"),
    group_by: str = typer.Option("bee", "--group-by", "-g", help="Group by: bee, hive, provider, day"),
) -> None:
    """Show usage insights (token usage, costs, latency)."""
    from hobees.db.analytics import summary
    
    valid_windows = ["1h", "24h", "7d", "all"]
    if window not in valid_windows:
        console.print(f"{ERROR} Invalid window: {window}. Valid: {', '.join(valid_windows)}")
        raise typer.Exit(code=1)
    
    valid_groups = ["bee", "hive", "provider", "day"]
    if group_by not in valid_groups:
        console.print(f"{ERROR} Invalid group-by: {group_by}. Valid: {', '.join(valid_groups)}")
        raise typer.Exit(code=1)
    
    data = summary(window=window, group_by=group_by)  # type: ignore[arg-type]
    
    if not data:
        console.print(f"{WARN} No usage data for window={window}, group_by={group_by}.")
        return
    
    table = Table(title=f"Usage Insights (window={window}, group_by={group_by})")
    table.add_column(group_by.capitalize(), style="cyan")
    table.add_column("Events", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Total Tokens", justify="right")
    table.add_column("Cost (USD)", justify="right")
    table.add_column("Avg Latency (ms)", justify="right")
    
    total_events = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    
    for row in data:
        key = row.get("key", "N/A")
        events = row.get("events", 0)
        in_toks = row.get("input_tokens", 0)
        out_toks = row.get("output_tokens", 0)
        cost = row.get("estimated_cost_usd", 0.0)
        latency = row.get("avg_latency_ms", 0)
        
        table.add_row(
            str(key),
            f"{events:,}",
            f"{in_toks:,}",
            f"{out_toks:,}",
            f"{in_toks + out_toks:,}",
            f"${cost:.4f}",
            f"{latency:,}" if latency else "N/A",
        )
        total_events += events
        total_in += in_toks
        total_out += out_toks
        total_cost += cost
    
    # Add totals row
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{total_events:,}[/bold]",
        f"[bold]{total_in:,}[/bold]",
        f"[bold]{total_out:,}[/bold]",
        f"[bold]{total_in + total_out:,}[/bold]",
        f"[bold]${total_cost:.4f}[/bold]",
        "",
    )
    
    console.print(table)


@app.command()
def serve(
    port: int = typer.Option(8420, "--port", "-p", help="API bind port"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="API bind host"),
) -> None:
    """Launch the local FastAPI telemetry API."""
    import uvicorn
    from hobees.api.app import create_app
    
    console.print(f"{APP} Starting telemetry API on http://{host}:{port}")
    console.print(f"  Endpoints:")
    console.print(f"    GET  /health")
    console.print(f"    GET  /stats?window=all&group_by=bee")
    console.print(f"    GET  /stats/recent?limit=20")
    console.print(f"    GET  /runs/active")
    console.print(f"    GET  /runs/{{thread_id}}")
    
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


@app.command()
def web(
    port: int = typer.Option(6543, "--port", "-p", help="Web UI bind port"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Web UI bind host"),
    open_browser: bool = typer.Option(False, "--open", help="Open browser on startup"),
    read_only: bool = typer.Option(False, "--read-only", help="Disable mutating endpoints"),
) -> None:
    """Launch the hobees Web UI (Workbench, Studio & Trace Explorer)."""
    import threading
    import webbrowser
    import uvicorn
    from hobees.db.session import get_engine
    from hobees.web.app import create_web_app

    _ensure_database_initialized(get_engine())

    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}"
    console.print(f"{APP} Starting hobees Web UI on http://{host}:{port}")

    if read_only:
        console.print(f"  {WARN} Read-only mode enabled — mutating endpoints disabled.")
    elif host not in {"127.0.0.1", "localhost", "::1"}:
        console.print(
            f"  {WARN} [bold yellow]Security Warning:[/bold yellow] Binding to {host} without --read-only. "
            "Place this dashboard behind authentication (reverse proxy / VPN) because approving "
            "tool calls or running hives can execute file writes or commands."
        )

    web_app = create_web_app(read_only=read_only)

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(web_app, host=host, port=port, log_level="info")


@app.command()
def prompt(
    goal: str = typer.Argument(
        None,
        help="Goal to execute in single-shot print mode, or `-` to read it from stdin",
    ),
    provider: str = typer.Option(None, "--provider", help="Provider alias to use"),
    model: str = typer.Option(None, "--model", help="Model name to use"),
    thinking: str = typer.Option("medium", "--thinking", help="Thinking level: off, low, medium, high"),
    approval_mode: str = typer.Option(None, "--approval-mode", help="interactive|auto|strict|pause"),
    # Last, so `prompt(goal, provider, model, thinking)` positional calls keep working.
    goal_file: str = typer.Option(None, "--goal-file", help="Read the goal from a file (or - for stdin)"),
) -> None:
    """Execute a single goal non-interactively and exit (`-p` alias).

    The goal may also arrive from `--goal-file <path>` or a pipe, which is what makes
    a container/CI step readable when the prompt is long.
    """
    from hobees.cli.goal_input import require_goal, resolve_goal
    from hobees.db.session import get_engine, session_scope
    from hobees.db.models import LLMProvider, Bee, Hive, HiveMembership, Run
    from hobees.core.hive_builder import hive_app
    from hobees.cli.approval_cmd import normalize_level

    goal = require_goal(resolve_goal(goal, goal_file))

    # Only a real level string is trusted; anything else falls back to the
    # context default inside the graph.
    approval_level = normalize_level(approval_mode) if isinstance(approval_mode, str) else None
    
    engine = get_engine()
    db_url = engine.url
    
    with session_scope() as session:
        providers = session.query(LLMProvider).all()
    
    if not providers:
        console.print(f"{ERROR} No LLM providers configured. Run 'hobees provider add' first.")
        raise typer.Exit(code=1)
    
    # Select provider
    selected_provider = None
    if provider:
        selected_provider = next((p for p in providers if p.alias == provider), None)
        if not selected_provider:
            console.print(f"{ERROR} Provider '{provider}' not found.")
            raise typer.Exit(code=1)
    elif len(providers) == 1:
        selected_provider = providers[0]
    else:
        console.print(f"{ERROR} Multiple providers exist. Specify one with --provider.")
        raise typer.Exit(code=1)
    
    # Select model
    selected_model = model or selected_provider.default_model
    if not selected_model:
        console.print(f"{ERROR} No model specified and provider has no default.")
        raise typer.Exit(code=1)
    
    # Get available bees
    with session_scope() as session:
        bees = session.query(Bee).all()
    
    if not bees:
        console.print(f"{WARN} No Worker Bees registered — run 'hobees bee create' first.")
        raise typer.Exit(code=1)
    
    thread_id = uuid.uuid4().hex
    console.print(f"{APP} Executing goal: {goal}")
    console.print(f"  Provider: {selected_provider.alias} ({selected_provider.provider_type})")
    console.print(f"  Model: {selected_model}")
    console.print(f"  Thread: {thread_id}")
    console.print()
    
    try:
        with session_scope() as session:
            hive = Hive(
                name=f"prompt-{uuid.uuid4().hex[:8]}",
                goal_description=goal,
                supervisor_provider_id=selected_provider.id,
                supervisor_model_name=selected_model,
                supervisor_prompt=None,
                is_dynamic=True,
            )
            session.add(hive)
            session.flush()
            hive_id = hive.id
            for bee in bees:
                session.add(HiveMembership(hive_id=hive.id, bee_id=bee.id))
            run = Run(
                thread_id=thread_id,
                hive_id=hive.id,
                mode="auto",
                goal=goal,
                status="running",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        providers_dict = {p.id: p for p in providers}
        
        with hive_app(
            hive,
            bees,
            providers_dict,
            db_url,
            thread_id,
            run_id,
            thinking,
            approval_mode=approval_level,
        ) as app:
            result = app.invoke(
                {"messages": [("user", goal)]},
                config={"configurable": {"thread_id": thread_id}},
            )
        output = str(result)
        messages = result.get("messages", []) if isinstance(result, dict) else []
        # An approval interrupt means the goal was not finished - a headless run cannot answer it,
        # so the pipeline must see a non-zero code instead of a plain "completed".
        interrupts = result.get("__interrupt__", []) if isinstance(result, dict) else []
        status = "awaiting_approval" if interrupts else "completed"
        memory_output = (
            str(getattr(messages[-1], "content", messages[-1]))
            if messages
            else output
        )
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = status
                run.completed_at = datetime.now(timezone.utc)
        from hobees.core.memory_manager import extract_run_memories

        extract_run_memories(
            goal=goal,
            output=memory_output,
            provider=selected_provider,
            model_name=selected_model,
            hive_name=hive.name,
            source_thread_id=thread_id,
            allow_hive_facts=False,
        )
        from hobees.core.skill_harvester import harvest_completed_run

        skill_draft = harvest_completed_run(run_id)
        if status != "completed":
            console.print(f"{WARN} Goal stopped for approval ({len(interrupts)} pending decision(s))")
            from hobees.core.pipeline_status import pipeline_exit_code

            raise typer.Exit(code=pipeline_exit_code(status))
        console.print(f"{SUCCESS} Goal completed:")
        console.print(output)
        if skill_draft:
            console.print(
                f"{APP} Skill draft {skill_draft['name']!r} generated; "
                "review and save it with 'hobees skill save-last'."
            )
        
        # Show telemetry
        from hobees.db.analytics import run_thread_usage
        usage = run_thread_usage(thread_id)
        if usage:
            events = usage.get('events', 0) or 0
            in_toks = usage.get('input_tokens', 0) or 0
            out_toks = usage.get('output_tokens', 0) or 0
            cost = usage.get('estimated_cost_usd', 0) or 0.0
            console.print(f"\n  tokens: {in_toks:,} in / {out_toks:,} out • ${cost:.4f} • {events} calls")
        
    except Exception as exc:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = "failed"
                run.completed_at = None
        console.print(f"{ERROR} Execution failed: {exc}")
        raise typer.Exit(code=1)


@app.command(name="run")
def run_cmd(
    goal: Annotated[
        str | None,
        typer.Argument(help="Goal/instruction to execute, or `-` to read stdin"),
    ] = None,
    hive: Annotated[str | None, typer.Option("--hive", "-h", help="Specific hive name to run")] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="Provider alias (for auto-mode)")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model name (for auto-mode)")] = None,
    thinking: Annotated[str | None, typer.Option("--thinking", help="Thinking level: off|low|medium|high")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Quiet output")] = False,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Execution timeout in seconds")] = None,
    artifacts_dir: Annotated[str | None, typer.Option("--artifacts-dir", help="Directory for hive outputs")] = None,
    approval_mode: Annotated[str | None, typer.Option("--approval-mode", help="interactive|auto|strict|pause")] = None,
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Convenience alias for --approval-mode auto")] = False,
    goal_file: Annotated[
        str | None,
        typer.Option("--goal-file", help="Read the goal from a file (or - for stdin)"),
    ] = None,
) -> None:
    """Execute a goal non-interactively (headless / CI/CD mode).

    A long prompt is better carried by a file or a pipe than by shell quoting, so
    `--goal-file goal.txt`, `hobees run - < goal.txt`, and `hobees run "short goal"`
    all work; the goal argument wins over the file, the file over piped stdin.
    """
    from hobees.cli.goal_input import require_goal, resolve_goal

    goal_text = require_goal(resolve_goal(goal, goal_file))
    level = _approval_session_level(approval_mode, auto_approve)
    if hive:
        from hobees.cli.hive_cmd import cmd_hive_run

        cmd_hive_run(
            hive_name=hive,
            goal=goal_text,
            output_json=output_json,
            quiet=quiet,
            timeout=timeout,
            artifacts_dir=artifacts_dir,
            thinking=thinking,
            approval_mode=level,
        )
    else:
        prompt(goal=goal_text, provider=provider, model=model, thinking=thinking, approval_mode=level)


@app.command(name="shell")
def shell_cmd(
    hive: Annotated[str | None, typer.Option("--hive", "-h", help="Hive to activate for this session")] = None,
    approval_mode: Annotated[str | None, typer.Option("--approval-mode", help="Approval level for this session: interactive|auto|strict|pause")] = None,
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Convenience alias for --approval-mode auto")] = False,
) -> None:
    """Enter the interactive subshell (default when run with no arguments)."""
    from hobees.cli.shell import _shell_loop
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider
    
    with session_scope() as session:
        providers = session.query(LLMProvider).all()
    
    selected_provider = None
    if len(providers) == 1:
        selected_provider = providers[0]
    
    ctx_obj: dict[str, Any] = {}
    if hive:
        ctx_obj["active_hive"] = hive
    session_level = _approval_session_level(approval_mode, auto_approve)
    if session_level:
        ctx_obj["approval_mode"] = session_level

    _shell_loop(ctx_obj, selected_provider)


# Alias `-p <goal>` support: typer doesn't natively do short-option aliases on
# arguments, so `hobees -p "..."` is handled by rewriting sys.argv early.


def _handle_prompt_alias() -> None:
    """Rewrite sys.argv for `-p <goal>` -> `prompt <goal>` before Typer parses."""
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "-p":
        sys.argv = [sys.argv[0], "prompt", sys.argv[2]] + sys.argv[3:]


def main() -> None:
    """Entry point for console script."""
    _handle_prompt_alias()
    app()


if __name__ == "__main__":
    main()