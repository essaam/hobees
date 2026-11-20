"""LLM Provider Registry handlers.

Shared by the Typer CLI (`hobees provider ...`) and the interactive shell
slash commands (`/provider ...`). Heavy imports (langchain, sqlalchemy engine)
are local to each handler so shell startup stays fast.
"""

from __future__ import annotations

from typing import Annotated, List, Optional

import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table

from hobees.cli.icons import ERROR, SUCCESS, WARN

console = Console()

app = typer.Typer(
    name="provider",
    help="Manage the global LLM provider registry",
)

VALID_TYPES = ("openai", "anthropic", "google_genai", "openai_compatible")


# ---------------------------------------------------------------------------
# handlers (shared with shell.py)
# ---------------------------------------------------------------------------

def cmd_provider_add(
    alias: str,
    provider_type: str,
    base_url: str | None = None,
    api_key_env: str = "NONE",
    default_model: str | None = None,
    input_cost_per_1m: float = 0.0,
    output_cost_per_1m: float = 0.0,
    interactive: bool = False,
) -> None:
    """Register a new global LLM provider."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider
    from hobees.core.model_discovery import fetch_provider_models

    if provider_type not in VALID_TYPES:
        console.print(f"{ERROR} provider_type must be one of {VALID_TYPES}")
        raise typer.Exit(code=1)

    with session_scope() as session:
        existing = session.query(LLMProvider).filter_by(alias=alias).first()
        if existing:
            console.print(f"{ERROR} provider alias {alias!r} already registered")
            raise typer.Exit(code=1)

        # Interactive guide
        if interactive:
            console.print(f"\n[bold]Creating provider: {alias!r}[/bold]")
            console.print(f"[bold]Provider type: {provider_type}[/bold]")
            console.print("  This allows you to use local (llama.cpp, Ollama, vLLM) or remote (OpenAI, Anthropic, Gemini) models.")
            console.print("[dim]Confirm by pressing Enter...[/dim]")
            input()  # Wait for user to confirm

        row = LLMProvider(
            alias=alias,
            provider_type=provider_type,
            base_url=base_url,
            api_key_env=api_key_env,
            default_model=default_model,
            input_cost_per_1m=input_cost_per_1m,
            output_cost_per_1m=output_cost_per_1m,
        )
        session.add(row)
        session.flush()
        created_id = row.id

    console.print(
        f"{SUCCESS} Provider {alias!r} ({provider_type}) registered "
        f"(api_key_env={api_key_env}, id={created_id})"
    )

    # Note: Model auto-discovery is now handled by callers (interactive mode, shell, etc.)
    # This function no longer does auto-discovery to avoid duplicate calls


def cmd_provider_add_interactive() -> None:
    """Interactive provider creation for CLI (no args required)."""
    console.print("[bold]Create New Provider[/bold]")
    
    alias = Prompt.ask("Provider alias")
    provider_type = Prompt.ask("Provider type", choices=list(VALID_TYPES))
    
    base_url = None
    if provider_type == "openai_compatible":
        base_url = Prompt.ask("Base URL (e.g. http://localhost:8080/v1)")
    
    api_key_env = Prompt.ask("API key env var (or NONE)", default="NONE")
    
    # Fetch models first if openai_compatible
    models = []
    if provider_type == "openai_compatible" and base_url:
        console.print(f"\n[bold]Fetching available models from {base_url}...[/bold]")
        # Create a temporary provider object for discovery
        from hobees.db.models import LLMProvider
        temp_provider = LLMProvider(
            alias=alias,
            provider_type=provider_type,
            base_url=base_url,
            api_key_env=api_key_env,
        )
        from hobees.core.model_discovery import fetch_provider_models
        models = fetch_provider_models(temp_provider, refresh_cache=True)
        if models:
            console.print(f"[green]Discovered {len(models)} models.[/green]")
        else:
            console.print(f"{WARN} No models discovered. Check base_url and API key.")
    
    # Select model from discovered list
    default_model = None
    if models:
        console.print("\n[bold]Select default model:[/bold]")
        for idx, model in enumerate(sorted(models), 1):
            console.print(f"  [cyan]({idx})[/cyan] {model}")
        console.print("  [cyan](custom)[/cyan] Enter custom model name")
        
        choice = Prompt.ask("Selection", default="1")
        if choice.lower() == "custom":
            default_model = Prompt.ask("Enter model name").strip()
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(models):
                    default_model = models[idx]
            except ValueError:
                default_model = Prompt.ask("Enter model name").strip()
    else:
        default_model = Prompt.ask("Default model (optional)", default="")
        if not default_model:
            default_model = None
    
    input_cost = float(Prompt.ask("Input cost per 1M tokens (USD)", default="0"))
    output_cost = float(Prompt.ask("Output cost per 1M tokens (USD)", default="0"))
    
    # Now create the provider
    cmd_provider_add(
        alias, provider_type, base_url, api_key_env, default_model,
        input_cost, output_cost, interactive=False
    )
    
    # If we fetched models, update the provider with them
    if models:
        from hobees.db.session import session_scope
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=alias).first()
            if provider:
                provider.available_models = models
                from datetime import datetime, timezone
                provider.models_refreshed_at = datetime.now(timezone.utc)


def cmd_provider_list() -> None:
    """List all registered providers."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider

    with session_scope() as session:
        rows = session.query(LLMProvider).order_by(LLMProvider.alias).all()

    table = Table(title="Global LLM Provider Registry")
    table.add_column("alias", style="cyan")
    table.add_column("type")
    table.add_column("base_url")
    table.add_column("api_key_env")
    table.add_column("default_model")
    table.add_column("cost in/out per 1M")
    table.add_column("models")
    for p in rows:
        model_count = len(p.available_models) if p.available_models else 0
        table.add_row(
            p.alias,
            p.provider_type,
            p.base_url or "-",
            p.api_key_env,
            p.default_model or "-",
            f"${p.input_cost_per_1m} / ${p.output_cost_per_1m}",
            str(model_count),
        )
    if not rows:
        console.print(f"{WARN} No providers registered yet. Use /provider add.")
    else:
        console.print(table)


def cmd_provider_json_list() -> None:
    """List providers from JSON file (parallel to DB)."""
    import json
    path = _get_providers_json_path()
    if not path.exists():
        console.print(f"{WARN} No providers.json file found.")
        return
    with open(path, "r") as f:
        providers = json.load(f)
    table = Table(title="Providers (JSON file)")
    table.add_column("alias")
    table.add_column("type")
    table.add_column("base_url")
    for p in providers:
        table.add_row(
            p.get("alias", "-"),
            p.get("provider_type", "-"),
            p.get("base_url", "-") or "-",
        )
    console.print(table)


def cmd_provider_test(alias: str) -> None:
    """Health-check a registered provider (config + runtime API key presence)."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider
    from hobees.core.llm_factory import resolve_api_key  # lazy: langchain import

    with session_scope() as session:
        row = session.query(LLMProvider).filter_by(alias=alias).first()
    if not row:
        console.print(f"{ERROR} provider alias {alias!r} not found")
        raise typer.Exit(code=1)

    key = resolve_api_key(row)
    missing = row.api_key_env != "NONE" and not key
    if missing:
        console.print(
            f"{WARN} {alias!r}: provider config OK, but env var {row.api_key_env!r} "
            f"is not set in this environment."
        )
    else:
        console.print(
            f"{SUCCESS} {alias!r} ({row.provider_type}) healthy — "
            f"api_key_env={row.api_key_env}"
        )


def cmd_provider_remove(alias: str) -> None:
    """Remove a provider from the registry (blocked if bees reference it)."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider, Bee

    with session_scope() as session:
        row = session.query(LLMProvider).filter_by(alias=alias).first()
        if not row:
            console.print(f"{ERROR} provider alias {alias!r} not found")
            raise typer.Exit(code=1)
        bee_count = session.query(Bee).filter_by(provider_id=row.id).count()
        if bee_count:
            console.print(
                f"{ERROR} cannot remove {alias!r}: {bee_count} Bee(s) still reference it. "
                f"Re-assign or delete those Bees first."
            )
            raise typer.Exit(code=1)
        session.delete(row)
    console.print(f"{SUCCESS} Provider {alias!r} removed.")


def cmd_provider_edit(
    alias: str,
    provider_type: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    default_model: str | None = None,
    input_cost_per_1m: float | None = None,
    output_cost_per_1m: float | None = None,
    context_window_tokens: int | None = None,
) -> None:
    """Edit an existing provider's details."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider

    with session_scope() as session:
        row = session.query(LLMProvider).filter_by(alias=alias).first()
        if not row:
            console.print(f"{ERROR} provider alias {alias!r} not found")
            raise typer.Exit(code=1)

        updated = False
        if provider_type is not None:
            if provider_type not in VALID_TYPES:
                console.print(f"{ERROR} provider_type must be one of {VALID_TYPES}")
                raise typer.Exit(code=1)
            row.provider_type = provider_type
            updated = True

        if base_url is not None:
            row.base_url = base_url or None
            updated = True

        if api_key_env is not None:
            row.api_key_env = api_key_env
            updated = True

        if input_cost_per_1m is not None:
            row.input_cost_per_1m = input_cost_per_1m
            updated = True

        if output_cost_per_1m is not None:
            row.output_cost_per_1m = output_cost_per_1m
            updated = True

        if context_window_tokens is not None:
            row.context_window_tokens = context_window_tokens
            updated = True

        if updated:
            console.print(f"{SUCCESS} Provider {alias!r} updated")
        else:
            console.print(f"{WARN} No changes provided")


def cmd_provider_models(
    alias: str,
    refresh: bool = False,
) -> None:
    """Show available models for a provider (auto-discovery)."""
    from hobees.core.model_discovery import fetch_provider_models
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider

    with session_scope() as session:
        row = session.query(LLMProvider).filter_by(alias=alias).first()
    if not row:
        console.print(f"{ERROR} provider alias {alias!r} not found")
        raise typer.Exit(code=1)

    import os
    # Check if API key is set (for providers that require it)
    if row.api_key_env != "NONE" and not os.environ.get(row.api_key_env):
        console.print(f"{WARN} API key env var '{row.api_key_env}' is not set.")
        if Confirm.ask("Set api_key_env to NONE and try anyway? (you may have limited functionality)"):
            row.api_key_env = "NONE"
        else:
            return

    try:
        models = fetch_provider_models(row, refresh_cache=refresh)
    except Exception as e:
        console.print(f"{ERROR} Failed to fetch models: {e}")
        return

    if not models:
        console.print(f"{WARN} No models available for {alias!r} (or provider not yet configured).")
        return

    table = Table(title=f"{alias!r} — Available Models (refreshed={refresh})")
    table.add_column("index", style="blue")
    table.add_column("model", style="green")
    table.add_column("context", style="dim")
    for idx, model in enumerate(models, 1):
        table.add_row(
            str(idx).ljust(6),
            model.ljust(20),
            f"{row.context_window_tokens:,}" if row.context_window_tokens else "-",
        )
    console.print(table)

    # If there are models, show interactive picker hint
    if len(models) > 1:
        console.print(
            f"\n[bold]💡 Tip: Use the interactive picker during /bee create or /bee update "
            f"to select one of these models."
        )


def interactive_model_picker(models: List[str], default: Optional[str] = None) -> Optional[str]:
    """Present an interactive numbered/fuzzy model picker."""
    if not models:
        return default

    # Show models in a table
    console.print("\n[bold]Available models:[/bold]")
    for idx, model in enumerate(sorted(models), 1):
        prefix = f"[cyan]({idx})[/cyan]"
        if default == model:
            prefix += f" [dim](default)[/dim]"
        console.print(f"  {prefix} {model}")

    console.print("[dim]Enter number (1-{}) or model name, or 'custom' to type manually.[/dim]".format(len(models)))
    choice = Prompt.ask("Selection")

    if choice.lower() == "custom":
        return Prompt.ask("Enter model name").strip()

    # Try numeric selection
    try:
        num = int(choice)
        if 1 <= num <= len(models):
            return models[num - 1]
    except ValueError:
        pass

    # Try fuzzy match
    for model in models:
        if model.lower() in choice.lower():
            return model

    console.print(f"{WARN} Could not parse choice: {choice}")
    return default


# ---------------------------------------------------------------------------
# Typer CLI commands
# ---------------------------------------------------------------------------


@app.command(name="add")
def cli_add(
    alias: Annotated[str | None, typer.Argument(help="Provider alias (e.g. openai-main)")] = None,
    provider_type: Annotated[
        str | None, typer.Argument(help="openai | anthropic | google_genai | openai_compatible")
    ] = None,
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="Base URL for openai_compatible endpoints")
    ] = None,
    api_key_env: Annotated[
        str, typer.Option("--api-key-env", help="Env var name holding the key, or NONE")
    ] = "NONE",

    input_cost_per_1m: Annotated[
        float, typer.Option("--input-cost-per-1m", help="Input cost per 1M tokens (USD)")
    ] = 0.0,
    output_cost_per_1m: Annotated[
        float, typer.Option("--output-cost-per-1m", help="Output cost per 1M tokens (USD)")
    ] = 0.0,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Interactive mode")
    ] = False,
) -> None:
    if interactive or alias is None or provider_type is None:
        # Run interactive mode
        cmd_provider_add_interactive()
    else:
        cmd_provider_add(
            alias, provider_type, base_url, api_key_env, default_model,
            input_cost_per_1m, output_cost_per_1m,
        )


@app.command(name="list")
def cli_list() -> None:
    cmd_provider_list()


@app.command(name="test")
def cli_test(alias: Annotated[str, typer.Argument(help="Provider alias to test")]) -> None:
    cmd_provider_test(alias)


@app.command(name="remove")
def cli_remove(alias: Annotated[str, typer.Argument(help="Provider alias to remove")]) -> None:
    cmd_provider_remove(alias)


@app.command(name="edit")
def cli_edit(
    alias: Annotated[str, typer.Argument(help="Provider alias to edit")],
    provider_type: Annotated[
        str | None, typer.Option("--type", help="Provider type (openai, anthropic, google_genai, openai_compatible)")
    ] = None,
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="Base URL for openai_compatible endpoints")
    ] = None,
    api_key_env: Annotated[
        str | None, typer.Option("--api-key-env", help="Env var name holding the key, or NONE")
    ] = None,

    input_cost_per_1m: Annotated[
        float | None, typer.Option("--input-cost-per-1m", help="Input cost per 1M tokens (USD)")
    ] = None,
    output_cost_per_1m: Annotated[
        float | None, typer.Option("--output-cost-per-1m", help="Output cost per 1M tokens (USD)")
    ] = None,
    context_window_tokens: Annotated[
        int | None, typer.Option("--context-window", help="Context window tokens")
    ] = None,
) -> None:
    cmd_provider_edit(
        alias, provider_type, base_url, api_key_env, default_model,
        input_cost_per_1m, output_cost_per_1m, context_window_tokens,
    )


@app.command(name="models")
def cli_models(
    alias: Annotated[str, typer.Argument(help="Provider alias")],
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Refresh model cache from provider"),
    ] = False,
) -> None:
    cmd_provider_models(alias, refresh)


@app.command(name="use")
def cli_use(
    alias: Annotated[str, typer.Argument(help="Provider alias or number to switch to")],
) -> None:
    """Switch the session's default provider (updates assistant)."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider
    from hobees.cli.provider_cmd import cmd_provider_list

    with session_scope() as session:
        providers = session.query(LLMProvider).order_by(LLMProvider.id).all()

    if not providers:
        console.print(f"{ERROR} No providers registered.")
        raise typer.Exit(code=1)

    if alias.isdigit():
        idx = int(alias) - 1
        if 0 <= idx < len(providers):
            provider = providers[idx]
        else:
            console.print(f"{ERROR} Invalid provider number: {alias}")
            raise typer.Exit(code=1)
    else:
        provider = next((p for p in providers if p.alias == alias), None)
        if not provider:
            console.print(f"{ERROR} Provider {alias!r} not found.")
            raise typer.Exit(code=1)

    # Update the assistant's provider
    from hobees.db.models import Bee
    with session_scope() as session:
        assistant = session.query(Bee).filter_by(name="assistant").first()
        if assistant:
            assistant.provider_id = provider.id
            # Clear model so it picks up the new provider's default
            assistant.model_name = provider.default_model or ""
            console.print(f"{SUCCESS} Switched to provider: {provider.alias}")
        else:
            console.print(f"{WARN} No assistant bee found; created provider switch will apply on next launch")


__all__ = [
    "app",
    "cmd_provider_add",
    "cmd_provider_add_interactive",
    "cmd_provider_list",
    "cmd_provider_test",
    "cmd_provider_remove",
    "cmd_provider_edit",
    "cmd_provider_models",
    "cmd_provider_use",
    "VALID_TYPES",
    "interactive_model_picker",
]


# ---------------------------------------------------------------------------
# JSON file storage (parallel to Postgres)
# ---------------------------------------------------------------------------

def _get_providers_json_path() -> str:
    """Path to the JSON providers file."""
    from pathlib import Path
    home = Path.home() / ".hobees"
    home.mkdir(exist_ok=True)
    return home / "providers.json"


def _load_providers_from_json() -> list[dict]:
    """Load providers from JSON file."""
    import json
    path = _get_providers_json_path()
    if not path.exists():
        return []
    with open(path, "r") as f:
        return json.load(f)


def _save_providers_to_json(providers: list[dict]) -> None:
    """Save providers to JSON file."""
    import json
    path = _get_providers_json_path()
    with open(path, "w") as f:
        json.dump(providers, f, indent=2)


def _update_provider_json(providers: list[dict]) -> None:
    """Update the providers JSON file (parallel to DB)."""
    _save_providers_to_json(providers)