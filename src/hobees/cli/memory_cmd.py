"""Memory management handlers — shared by the Typer CLI (`hobees memory ...`)
and the interactive shell slash commands (`/memory ...`).

Cross-session scoped memory store with namespaces:
- global
- hive:<name>
- bee:<name>
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from hobees.cli.icons import ERROR, MEMORY, SUCCESS, WARN
from hobees.core.memory_manager import (
    upsert_memory,
    delete_memory,
    list_memories,
    build_memory_block,
    extract_namespaces,
)

console = Console()

app = typer.Typer(name="memory", help="Cross-session scoped memory store")


def cmd_memory_list(namespace: str | None = None) -> None:
    """List stored memories, optionally filtered by namespace."""
    memories = list_memories(namespace)
    if not memories:
        console.print(f"{WARN} No memories found.")
        return

    table = Table(title="Long-Term Memories")
    table.add_column("namespace", style="cyan")
    table.add_column("key", style="green")
    table.add_column("content")
    table.add_column("updated")
    for m in memories:
        content_preview = m["content"][:80] + ("..." if len(m["content"]) > 80 else "")
        table.add_row(
            m["namespace"],
            m["key"],
            content_preview,
            m["updated_at"] or "-",
        )
    console.print(table)


def cmd_memory_add(key: str, content: str, namespace: str = "global") -> None:
    """Add or update a memory entry."""
    valid_prefixes = ("global", "hive:", "bee:")
    if not any(namespace.startswith(p) for p in valid_prefixes):
        console.print(f"{ERROR} namespace must start with one of {valid_prefixes}")
        raise typer.Exit(code=1)

    upsert_memory(namespace, key, content)
    console.print(f"{SUCCESS} Memory added: [{namespace}] {key} = {content[:100]}")


def cmd_memory_forget(key: str, namespace: str = "global") -> None:
    """Delete a memory entry."""
    deleted = delete_memory(namespace, key)
    if deleted:
        console.print(f"{SUCCESS} Memory forgotten: [{namespace}] {key}")
    else:
        console.print(f"{WARN} Memory not found: [{namespace}] {key}")


def cmd_memory_show(key: str, namespace: str = "global") -> None:
    """Show full content of a memory entry."""
    memories = list_memories(namespace)
    for m in memories:
        if m["key"] == key:
            console.print(f"[bold]{m['namespace']}/{m['key']}[/bold]")
            console.print(m["content"])
            return
    console.print(f"{WARN} Memory not found: [{namespace}] {key}")


# ---------------------------------------------------------------------------
# Typer CLI commands
# ---------------------------------------------------------------------------


@app.command(name="list")
def cli_list(
    namespace: Annotated[str | None, typer.Option("--namespace", "-n", help="Filter by namespace prefix")] = None,
) -> None:
    cmd_memory_list(namespace)


@app.command(name="add")
def cli_add(
    key: Annotated[str, typer.Argument(help="Memory key")],
    content: Annotated[str, typer.Argument(help="Memory content")],
    namespace: Annotated[str, typer.Option("--namespace", "-n", help="global | hive:<name> | bee:<name>")] = "global",
) -> None:
    cmd_memory_add(key, content, namespace)


@app.command(name="forget")
def cli_forget(
    key: Annotated[str, typer.Argument(help="Memory key")],
    namespace: Annotated[str, typer.Option("--namespace", "-n", help="global | hive:<name> | bee:<name>")] = "global",
) -> None:
    cmd_memory_forget(key, namespace)


@app.command(name="show")
def cli_show(
    key: Annotated[str, typer.Argument(help="Memory key")],
    namespace: Annotated[str, typer.Option("--namespace", "-n", help="global | hive:<name> | bee:<name>")] = "global",
) -> None:
    cmd_memory_show(key, namespace)


__all__ = [
    "app",
    "cmd_memory_list",
    "cmd_memory_add",
    "cmd_memory_forget",
    "cmd_memory_show",
]