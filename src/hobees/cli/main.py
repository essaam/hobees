"""``hobees`` / ``hobiz`` Typer entrypoint.

CLI command modules are imported to register commands; database, model, and
API services are loaded lazily by execution handlers. No cold-start timing
target has been measured.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from hobees.cli.icons import APP, ERROR, SUCCESS, WARN
from hobees.cli.bee_cmd import app as bee_app
from hobees.cli.hive_cmd import app as hive_app
from hobees.cli.provider_cmd import app as provider_app
from hobees.cli.memory_cmd import app as memory_app
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
app.command(name="import")(import_config)


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
) -> None:
    """hobees — run with no arguments to enter the interactive shell."""
    if not ctx.resilient_parsing and ctx.invoked_subcommand not in ("init", "import"):
        from hobees.config import settings

        if settings.config_path:
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
        }
        from hobees.db.session import get_engine, session_scope
        from hobees.db.models import LLMProvider
        
        with session_scope() as session:
            providers = session.query(LLMProvider).all()
            engine = get_engine()
            db_url = engine.url
            
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
    
    # Create new tables if they don't exist (memories, skills, bee_skills)
    # These will be created by Base.metadata.create_all() anyway


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
) -> None:
    """Create database tables and optionally auto-import config.

    Creates the SQLAlchemy schema and initializes PostgreSQL checkpoints when
    applicable. Configure HOBEES_DATABASE_URL in ~/.hobees/.env or .env.
    PostgreSQL is recommended; SQLite is supported for local use. Also runs
    migrations for existing databases and imports config if specified.
    """
    from hobees.db.session import get_engine
    from hobees.db.models import Base

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
def prompt(
    goal: str = typer.Argument(..., help="Goal to execute in single-shot print mode"),
    provider: str = typer.Option(None, "--provider", help="Provider alias to use"),
    model: str = typer.Option(None, "--model", help="Model name to use"),
    thinking: str = typer.Option("medium", "--thinking", help="Thinking level: off, low, medium, high"),
) -> None:
    """Execute a single goal non-interactively and exit (`-p` alias)."""
    from hobees.db.session import get_engine, session_scope
    from hobees.db.models import LLMProvider, Bee, Hive, HiveMembership, Run
    from hobees.core.hive_builder import hive_app
    
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
        
        with hive_app(hive, bees, providers_dict, db_url, thread_id, run_id, thinking) as app:
            result = app.invoke(
                {"messages": [("user", goal)]},
                config={"configurable": {"thread_id": thread_id}},
            )
        output = str(result)
        messages = result.get("messages", []) if isinstance(result, dict) else []
        memory_output = (
            str(getattr(messages[-1], "content", messages[-1]))
            if messages
            else output
        )
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = "completed"
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
    goal: Annotated[str, typer.Argument(help="Goal/instruction to execute")],
    hive: Annotated[str | None, typer.Option("--hive", "-h", help="Specific hive name to run")] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="Provider alias (for auto-mode)")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model name (for auto-mode)")] = None,
    thinking: Annotated[str | None, typer.Option("--thinking", help="Thinking level: off|low|medium|high")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Quiet output")] = False,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Execution timeout in seconds")] = None,
    artifacts_dir: Annotated[str | None, typer.Option("--artifacts-dir", help="Directory for hive outputs")] = None,
) -> None:
    """Execute a goal non-interactively (headless / CI/CD mode)."""
    if hive:
        from hobees.cli.hive_cmd import cmd_hive_run

        cmd_hive_run(
            hive_name=hive,
            goal=goal,
            output_json=output_json,
            quiet=quiet,
            timeout=timeout,
            artifacts_dir=artifacts_dir,
            thinking=thinking,
        )
    else:
        prompt(goal=goal, provider=provider, model=model, thinking=thinking)


@app.command(name="shell")
def shell_cmd(
    hive: Annotated[str | None, typer.Option("--hive", "-h", help="Hive to activate for this session")] = None,
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
    
    _shell_loop({"active_hive": hive} if hive else {}, selected_provider)


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