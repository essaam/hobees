"""Worker Bee handlers — shared by the Typer CLI (`hobees bee ...`) and the
interactive shell slash commands (`/bee ...`).

Bees exist independently of Hives and can belong to zero, one, or many Hives.
"""

from __future__ import annotations

from typing import Annotated, List, Optional

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from hobees.cli.icons import BEE, ERROR, SUCCESS, WARN
from hobees.cli.provider_cmd import interactive_model_picker

console = Console()

app = typer.Typer(name="bee", help="Manage reusable Worker Bees")

# ---------------------------------------------------------------------------
# handlers (shared with shell.py)
# ---------------------------------------------------------------------------

def _parse_tool_names(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        import json

        return json.loads(raw)
    return [t.strip() for t in raw.split(",") if t.strip()]


def cmd_bee_create(
    name: str,
    role_description: str,
    system_prompt: str,
    provider_id: int,
    model_name: str,
    temperature: float = 0.0,
    tool_names: str = "",
    thinking_level: str = "off",
    require_approval: str = "",
) -> None:
    """Create a new Worker Bee."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, LLMProvider
    from hobees.core.model_discovery import fetch_provider_models

    tools = _parse_tool_names(tool_names)
    approval_tools = _parse_tool_names(require_approval)
    unknown = [name for name in approval_tools if name not in tools]
    if unknown:
        console.print(
            f"{WARN} require_approval tools must also be in tools: {', '.join(unknown)}"
        )
    with session_scope() as session:
        provider = session.get(LLMProvider, provider_id)
        if not provider:
            console.print(f"{ERROR} provider id {provider_id} not found")
            raise typer.Exit(code=1)
        if session.query(Bee).filter_by(name=name).first():
            console.print(f"{ERROR} Bee {name!r} already exists")
            raise typer.Exit(code=1)

        # Interactive model picker if available
        if provider and model_name:
            models = fetch_provider_models(provider, refresh_cache=False)
            if models:
                selected = interactive_model_picker(models, default=model_name)
                if selected is not None:
                    model_name = selected

        bee = Bee(
            name=name,
            role_description=role_description,
            system_prompt=system_prompt,
            provider_id=provider_id,
            model_name=model_name,
            temperature=temperature,
            thinking_level=thinking_level,
            tool_names=tools,
            require_approval=approval_tools,
        )
        session.add(bee)
        session.flush()
        bee_id = bee.id
    console.print(
        f"{SUCCESS} Bee {name!r} created (id={bee_id}, model={model_name}, "
        f"thinking={thinking_level}, tools={tools or '-'})"
    )


def cmd_bee_list() -> None:
    """List all Worker Bees with their provider and model."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, LLMProvider

    with session_scope() as session:
        rows = (
            session.query(Bee)
            .join(LLMProvider, Bee.provider_id == LLMProvider.id)
            .order_by(Bee.name)
            .all()
        )

    table = Table(title="Worker Bees")
    table.add_column("name", style="cyan")
    table.add_column("provider", style="green")
    table.add_column("model")
    table.add_column("temp")
    table.add_column("thinking")
    table.add_column("tools")
    for b in rows:
        table.add_row(
            b.name,
            b.provider.alias,
            b.model_name,
            str(b.temperature),
            b.thinking_level,
            ", ".join(b.tool_names) or "-",
        )
    if not rows:
        console.print(f"{WARN} No Bees registered yet. Use /bee create.")
    else:
        console.print(table)


def cmd_bee_update(
    name: str,
    provider_id: int | None = None,
    model_name: str | None = None,
    temperature: float | None = None,
    thinking_level: str | None = None,
    system_prompt: str | None = None,
    role_description: str | None = None,
    tool_names: str = "",
    require_approval: str = "",
) -> None:
    """Hot-swap provider, model, temperature, tools, or prompts mid-session."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, LLMProvider
    from hobees.core.model_discovery import fetch_provider_models

    valid_thinking = ("off", "low", "medium", "high")
    if thinking_level is not None and thinking_level not in valid_thinking:
        console.print(f"{ERROR} thinking level must be one of {valid_thinking}")
        raise typer.Exit(code=1)

    with session_scope() as session:
        bee = session.query(Bee).filter_by(name=name).first()
        if not bee:
            console.print(f"{ERROR} Bee {name!r} not found")
            raise typer.Exit(code=1)
        if provider_id is not None:
            provider = session.get(LLMProvider, provider_id)
            if not provider:
                console.print(f"{ERROR} provider id {provider_id} not found")
                raise typer.Exit(code=1)
            bee.provider_id = provider_id
            provider = provider
        else:
            provider = session.get(LLMProvider, bee.provider_id)
        if model_name is not None:
            bee.model_name = model_name
        if temperature is not None:
            bee.temperature = temperature
        if thinking_level is not None:
            bee.thinking_level = thinking_level
        if system_prompt is not None:
            bee.system_prompt = system_prompt
        if role_description is not None:
            bee.role_description = role_description
        if tool_names != "":
            bee.tool_names = _parse_tool_names(tool_names)
        if require_approval != "":
            approval_tools = _parse_tool_names(require_approval)
            unknown = [name for name in approval_tools if name not in bee.tool_names]
            if unknown:
                console.print(
                    f"{WARN} require_approval tools must also be in tools: {', '.join(unknown)}"
                )
            bee.require_approval = approval_tools

        # Interactive model picker if model changed and provider has models
        if model_name is not None and provider:
            models = fetch_provider_models(provider, refresh_cache=False)
            if models:
                selected = interactive_model_picker(models, default=model_name)
                if selected is not None:
                    bee.model_name = selected
                    console.print(f"[dim]Model updated to: {selected}[/dim]")

    console.print(f"{SUCCESS} Bee {name!r} updated.")


def cmd_bee_delete(name: str) -> None:
    """Delete a Bee (also removes its Hive memberships)."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, HiveMembership

    with session_scope() as session:
        bee = session.query(Bee).filter_by(name=name).first()
        if not bee:
            console.print(f"{ERROR} Bee {name!r} not found")
            raise typer.Exit(code=1)
        session.query(HiveMembership).filter_by(bee_id=bee.id).delete()
        session.delete(bee)
    console.print(f"{SUCCESS} Bee {name!r} deleted.")


def cmd_bee_thinking(name: str, level: str) -> None:
    """Set a Bee's default thinking level."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee

    valid_levels = ("off", "low", "medium", "high")
    if level not in valid_levels:
        console.print(f"{ERROR} thinking level must be one of {valid_levels}")
        raise typer.Exit(code=1)

    with session_scope() as session:
        bee = session.query(Bee).filter_by(name=name).first()
        if not bee:
            console.print(f"{ERROR} Bee {name!r} not found")
            raise typer.Exit(code=1)
        bee.thinking_level = level
    console.print(f"{SUCCESS} Bee {name!r} thinking level set to '{level}'")


# ---------------------------------------------------------------------------
# Typer CLI commands
# ---------------------------------------------------------------------------


@app.command(name="create")
def cli_create(
    name: Annotated[str, typer.Argument(help="Unique Bee name")],
    role_description: Annotated[str, typer.Argument(help="Role read by Supervisors/Queen for routing")],
    system_prompt: Annotated[str, typer.Argument(help="System prompt for the Bee")],
    provider_id: Annotated[int, typer.Argument(help="Registered LLM provider id")],
    model_name: Annotated[str, typer.Argument(help="Model name")],
    temperature: Annotated[float, typer.Option("--temperature", "-t")] = 0.0,
    tool_names: Annotated[
        str, typer.Option("--tool-names", help="Comma-separated or JSON list of tool keys")
    ] = "",
    thinking_level: Annotated[str, typer.Option("--thinking", help="off | low | medium | high")] = "off",
) -> None:
    cmd_bee_create(name, role_description, system_prompt, provider_id, model_name, temperature, tool_names, thinking_level)


@app.command(name="list")
def cli_list() -> None:
    cmd_bee_list()


@app.command(name="update")
def cli_update(
    name: Annotated[str, typer.Argument(help="Bee name")],
    provider_id: Annotated[int | None, typer.Option("--provider-id")] = None,
    model_name: Annotated[str | None, typer.Option("--model-name")] = None,
    temperature: Annotated[float | None, typer.Option("--temperature", "-t")] = None,
    thinking_level: Annotated[str | None, typer.Option("--thinking", help="off | low | medium | high")] = None,
    system_prompt: Annotated[str | None, typer.Option("--system-prompt")] = None,
    role_description: Annotated[str | None, typer.Option("--role-description")] = None,
    tool_names: Annotated[str, typer.Option("--tool-names")] = "",
) -> None:
    cmd_bee_update(
        name, provider_id, model_name, temperature, thinking_level, system_prompt, role_description, tool_names
    )


@app.command(name="delete")
def cli_delete(name: Annotated[str, typer.Argument(help="Bee name")]) -> None:
    cmd_bee_delete(name)


@app.command(name="thinking")
def cli_thinking(
    name: Annotated[str, typer.Argument(help="Bee name")],
    level: Annotated[str, typer.Argument(help="off | low | medium | high")],
) -> None:
    cmd_bee_thinking(name, level)


__all__ = [
    "app",
    "cmd_bee_create",
    "cmd_bee_list",
    "cmd_bee_update",
    "cmd_bee_delete",
    "cmd_bee_thinking",
    "_parse_tool_names",
]