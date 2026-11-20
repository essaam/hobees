"""Interactive shell for the Hobees CLI (FR-3, FR-4, FR-6, v1.1).

The shell provides slash commands for:

* ``/provider`` — LLM provider management & model discovery
* ``/bee`` — Worker Bee management
* ``/hive`` — Working Hive (team) management
* ``/chat`` — Chat directly with a Bee or Hive (or default assistant)
* ``/goal`` — Run a goal through the Queen (auto-mode)
* ``/hive use <name>`` — Lock subshell to a specific Hive
* ``/hive auto`` — Switch back to Queen auto-mode
* ``/usage`` — Query usage telemetry
* ``/thinking`` — Set session-wide thinking level override
* ``/compact`` — Compress active thread's message history
* ``/memory`` — Cross-session scoped memory store
* ``/skill`` — Progressive skill library
* ``/session`` — Named session management (save, load, list)
* ``/quit`` / ``/exit`` — Exit the shell
* ``/help`` — List commands

All heavy imports are lazy (Section 3.1).
"""

from __future__ import annotations

import sys
import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.panel import Panel

from hobees.cli.provider_cmd import VALID_TYPES
from hobees.cli.provider_cmd import cmd_provider_add as provider_add
from hobees.cli.provider_cmd import cmd_provider_list as provider_list
from hobees.cli.provider_cmd import cmd_provider_test as provider_test
from hobees.cli.provider_cmd import cmd_provider_remove as provider_remove
from hobees.cli.provider_cmd import cmd_provider_models as provider_models
from hobees.cli.provider_cmd import interactive_model_picker
from hobees.cli.bee_cmd import cmd_bee_create, cmd_bee_list, cmd_bee_update, cmd_bee_delete, cmd_bee_thinking
from hobees.cli.hive_cmd import cmd_hive_create, cmd_hive_add_bee, cmd_hive_remove_bee, cmd_hive_list, cmd_hive_remove_interactive, cmd_hive_thinking
from hobees.cli.memory_cmd import cmd_memory_list, cmd_memory_add, cmd_memory_forget, cmd_memory_show
from hobees.cli.skill_cmd import cmd_skill_list, cmd_skill_show, cmd_skill_create, cmd_skill_save_last, cmd_skill_assign, cmd_skill_unassign, cmd_skill_sync
from hobees.core.hive_builder import hive_app
from hobees.core.streaming import DeltaStreamer
from hobees.core.queen import Queen, build_queen
from hobees.core.model_discovery import fetch_provider_models
from hobees.db.models import Bee, Hive, HiveMembership, LLMProvider, Run
from sqlalchemy.orm import joinedload
from hobees.db.session import session_scope, get_engine

from hobees.db.analytics import summary as get_summary  # noqa: F401
from hobees.cli.icons import (
    APP, BEE, HIVE, QUEEN, PROVIDER, TOOL, ACTIVE,
    SUCCESS, WARN, ERROR, MEMORY, SKILL, COMPACT, THINKING
)

console = Console()

# -- Command registry ----------------------------------------------------

# Slash-command catalog lives in one place, shared with the TUI and its
# completion menu.
from hobees.cli.commands import COMMANDS as _COMMANDS


def _parse_args(args: list[str]) -> tuple[str, list[str]]:
    """Split command + optional args."""
    if not args:
        return "", []
    cmd = args[0].lstrip("/").lower()
    rest = args[1:] if len(args) > 1 else []
    return cmd, rest


# -- Session Management ---------------------------------------------------

_SESSION_DIR = Path.home() / ".hobees" / "sessions"
_SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _get_session_file(name: str) -> Path:
    return _SESSION_DIR / f"{name}.json"


def _save_session(name: str, data: dict) -> None:
    import json
    _get_session_file(name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_session(name: str) -> dict | None:
    import json
    path = _get_session_file(name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _list_sessions() -> list[str]:
    return [f.stem for f in _SESSION_DIR.glob("*.json")]


def _delete_session(name: str) -> bool:
    path = _get_session_file(name)
    if path.exists():
        path.unlink()
        return True
    return False


def _capture_session_state(active_hive: str | None = None, thread_id: str | None = None) -> dict:
    """Capture current shell state for session saving."""
    with session_scope() as session:
        providers = session.query(LLMProvider).all()
        bees = session.query(Bee).all()
        hives = session.query(Hive).all()

    return {
        "active_hive": active_hive,
        "thread_id": thread_id,
        "timestamp": str(uuid.uuid4()),
        "providers": [{"alias": p.alias, "type": p.provider_type} for p in providers],
        "bees": [{"name": b.name, "provider": b.provider_id} for b in bees],
        "hives": [{"name": h.name, "dynamic": h.is_dynamic} for h in hives],
    }


def _get_checkpointer(db_url):
    """Get the appropriate checkpointer for the database type."""
    import sqlite3

    from hobees.db.backends import get_database_backend, get_postgres_checkpoint_url

    if get_database_backend(db_url) == "sqlite":
        from sqlalchemy.engine import make_url

        sqlite_path = make_url(db_url).database
        if not sqlite_path or sqlite_path == ":memory:":
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver(), None

        from langgraph.checkpoint.sqlite import SqliteSaver

        connection = sqlite3.connect(sqlite_path, check_same_thread=False)
        saver = SqliteSaver(connection)
    else:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import connect

        connection = connect(
            get_postgres_checkpoint_url(db_url),
            autocommit=True,
            prepare_threshold=0,
        )
        saver = PostgresSaver(connection)

    try:
        saver.setup()
    except Exception:
        connection.close()
        raise
    return saver, connection


# -- Helper functions -----------------------------------------------------

def _ensure_default_assistant(provider: LLMProvider, db_url: str) -> Bee | None:
    """Create a default assistant bee if it doesn't exist. Returns the assistant bee."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee

    with session_scope() as session:
        assistant = session.query(Bee).filter_by(name="assistant").first()
        if not assistant:
            # Use provider's default_model as fallback
            assistant_model_name = provider.default_model or "gpt-4o-mini"
            assistant = Bee(
                name="assistant",
                role_description="General-purpose assistant that can help with setup, answer questions, and execute tasks using available tools.",
                system_prompt="You are a helpful AI assistant. You can use tools to read/write files, run calculations, and help the user set up providers, bees, and hives. Be friendly and proactive in helping them get started.",
                provider_id=provider.id,
                model_name=assistant_model_name,
                temperature=0.7,
                thinking_level="off",
                tool_names=["read_file", "write_file", "list_directory", "run_python_calc", "save_memory", "recall_memory"],
            )
            session.add(assistant)
            session.flush()
            assistant_id = assistant.id
            console.print(f"{SUCCESS} Created default assistant bee: {BEE} assistant")
            console.print(f"  Use '/chat bee assistant' to start chatting, or '/goal' for auto-mode.")
            return assistant
    return None


def _get_or_create_assistant(provider: LLMProvider, db_url: str) -> Bee:
    """Get the default assistant bee, creating it if it doesn't exist.

    If the assistant exists but its provider differs from the passed provider,
    update it to match the current session's provider. This ensures the chat
    uses the provider the user has currently selected.
    """
    from hobees.db.session import session_scope
    from hobees.db.models import Bee

    with session_scope() as session:
        assistant = session.query(Bee).filter_by(name="assistant").first()
        if assistant:
            # Sync provider_id to match the current session's provider
            if assistant.provider_id != provider.id:
                assistant.provider_id = provider.id
            return assistant

    # Create if not found
    _ensure_default_assistant(provider, db_url)
    with session_scope() as session:
        return session.query(Bee).filter_by(name="assistant").first()


def get_assistant_selection() -> tuple["LLMProvider | None", str | None]:
    """Return the provider and model the default assistant is configured with.

    ``(None, None)`` means there is no assistant yet (or its provider was
    deleted), in which case the caller picks a provider itself.
    """
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, LLMProvider

    with session_scope() as session:
        assistant = session.query(Bee).filter_by(name="assistant").first()
        if not assistant:
            return None, None
        provider = session.get(LLMProvider, assistant.provider_id)
        if not provider:
            return None, None
        return provider, assistant.model_name


def persist_assistant_selection(provider_id: int, model_name: str | None) -> None:
    """Save the assistant's provider/model so the next launch starts with it."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee

    with session_scope() as session:
        assistant = session.query(Bee).filter_by(name="assistant").first()
        if not assistant:
            return
        assistant.provider_id = provider_id
        if model_name:
            assistant.model_name = model_name


def _ask_provider_alias(prompt: str = "Provider (alias or number, Enter to cancel)") -> str:
    """Ask which provider to use, offering a list. Blank input cancels."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider

    with session_scope() as session:
        providers = session.query(LLMProvider).order_by(LLMProvider.id).all()

    if not providers:
        console.print(f"{WARN} No providers registered yet. Use /provider add.")
        return ""

    if len(providers) == 1:
        return providers[0].alias

    for idx, p in enumerate(providers, 1):
        console.print(f"  [cyan]({idx})[/cyan] {p.alias} ({p.provider_type})")

    answer = Prompt.ask(prompt, default="").strip()
    if not answer or answer.lower() in ("exit", "quit"):
        return ""
    if answer.isdigit():
        idx = int(answer) - 1
        if 0 <= idx < len(providers):
            return providers[idx].alias
        console.print(f"{ERROR} No provider number {answer}.")
        return ""
    # Check if it's a valid alias
    if not any(p.alias == answer for p in providers):
        console.print(f"{ERROR} Provider {answer!r} not found.")
        return ""
    return answer


def _resolve_provider_in_session(session, alias_or_num: str):
    """Look a provider up by alias or by its 1-based position in the list, using an existing session."""
    from hobees.db.models import LLMProvider

    if alias_or_num.isdigit():
        providers = session.query(LLMProvider).order_by(LLMProvider.id).all()
        idx = int(alias_or_num) - 1
        return providers[idx] if 0 <= idx < len(providers) else None
    return session.query(LLMProvider).filter_by(alias=alias_or_num).first()


def _resolve_provider(alias_or_num: str):
    """Look a provider up by alias or by its 1-based position in the list."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider

    with session_scope() as session:
        if alias_or_num.isdigit():
            providers = session.query(LLMProvider).order_by(LLMProvider.id).all()
            idx = int(alias_or_num) - 1
            return providers[idx] if 0 <= idx < len(providers) else None
        return session.query(LLMProvider).filter_by(alias=alias_or_num).first()


# -- Handler functions ----------------------------------------------------

def _handle_provider(args: list[str], shell_state: dict) -> None:
    if not args:
        console.print(f"[bold]Provider commands:[/bold] add, list, test, remove, edit, models, use")
        return

    cmd, rest = _parse_args(args)

    if cmd == "add":
        # Use the interactive provider creation which includes model discovery
        from hobees.cli.provider_cmd import cmd_provider_add_interactive
        cmd_provider_add_interactive()
        # After adding, update shell_state provider if none was selected
        if shell_state.get("provider") is None:
            with session_scope() as session:
                providers = session.query(LLMProvider).all()
                if len(providers) == 1:
                    shell_state["provider"] = providers[0]
                    console.print(f"{SUCCESS} Now using provider: {providers[0].alias}")
                elif len(providers) > 1:
                    console.print(f"{WARN} Multiple providers exist. Use /provider list to see them.")

    elif cmd == "list":
        provider_list()

    elif cmd == "test":
        alias = _ask_provider_alias()
        if not alias:
            return
        provider_test(alias)

    elif cmd == "remove":
        alias = _ask_provider_alias("Provider to remove (alias or number, Enter to cancel)")
        if not alias:
            return
        provider_remove(alias)

    elif cmd == "edit":
        # Edit an existing provider's details
        alias = rest[0] if rest else _ask_provider_alias("Provider to edit (alias or number, Enter to cancel)")
        if not alias:
            return
        
        # Fetch and update in a single session to persist changes
        from hobees.db.session import session_scope
        from hobees.db.models import LLMProvider
        
        with session_scope() as session:
            provider = _resolve_provider_in_session(session, alias)
            if not provider:
                console.print(f"{ERROR} Provider {alias!r} not found")
                return
            
            console.print(
                f"Editing provider: {provider.alias} ({provider.provider_type})"
            )
            console.print("Press Enter to keep current value.")
            
            # Provider type (usually shouldn't change, but allow it)
            new_type = Prompt.ask("Provider type", choices=["openai", "anthropic", "google_genai", "openai_compatible"], default=provider.provider_type)
            if new_type:
                provider.provider_type = new_type
            
            # Base URL
            new_base_url = Prompt.ask("Base URL", default=provider.base_url or "").strip() or None
            if new_base_url:
                provider.base_url = new_base_url
            elif new_base_url == "":
                provider.base_url = None
            
            # API key env var
            new_api_key_env = Prompt.ask("API key env var (or NONE)", default=provider.api_key_env)
            if new_api_key_env:
                provider.api_key_env = new_api_key_env
            
            # Input/output costs
            new_input_cost = Prompt.ask("Input cost per 1M tokens (USD)", default=str(provider.input_cost_per_1m))
            try:
                provider.input_cost_per_1m = float(new_input_cost)
            except ValueError:
                console.print(f"{WARN} Invalid input cost, keeping current")
            
            new_output_cost = Prompt.ask("Output cost per 1M tokens (USD)", default=str(provider.output_cost_per_1m))
            try:
                provider.output_cost_per_1m = float(new_output_cost)
            except ValueError:
                console.print(f"{WARN} Invalid output cost, keeping current")
            
            # Context window
            new_context = Prompt.ask("Context window tokens", default=str(provider.context_window_tokens))
            try:
                provider.context_window_tokens = int(new_context)
            except ValueError:
                console.print(f"{WARN} Invalid context window, keeping current")
            
            # If type changed to openai_compatible and no base_url, ask for it
            if provider.provider_type == "openai_compatible" and not provider.base_url:
                new_base_url = Prompt.ask("Base URL (required for openai_compatible)", default="").strip()
                if new_base_url:
                    provider.base_url = new_base_url
                else:
                    console.print(f"{WARN} openai_compatible providers require a base_url")
            
            # session_scope commits on exit
            console.print(f"{SUCCESS} Provider {provider.alias!r} updated")

    elif cmd == "models":
        # Read-only: list the models discovered for a provider.
        positional = [a for a in rest if not a.startswith("--")]
        alias = positional[0] if positional else _ask_provider_alias()
        if not alias:
            console.print(f"{WARN} No provider selected — nothing to show.")
            return
        refresh = "--refresh" in rest
        provider_models(alias, refresh)

    elif cmd == "use":
        # Switch the session's provider. The model follows: keep the assistant's
        # model when the provider did not change, otherwise use the provider's
        # configured default (and offer a picker if it has none).
        alias = rest[0] if rest else _ask_provider_alias()
        provider = _resolve_provider(alias)
        if not provider:
            console.print(f"{ERROR} Provider {alias!r} not found")
            return

        shell_state["provider"] = provider
        assistant_provider, assistant_model = get_assistant_selection()
        if assistant_provider is not None and assistant_provider.id == provider.id and assistant_model:
            model_name = assistant_model
        elif provider.default_model:
            model_name = provider.default_model
        else:
            from hobees.core.model_discovery import fetch_provider_models

            model_name = None
            models = fetch_provider_models(provider, refresh_cache=False)
            if models:
                if len(models) == 1:
                    model_name = models[0]
                else:
                    console.print(f"\nAvailable models for {provider.alias}:")
                    model_name = interactive_model_picker(models, default=None)

        shell_state["default_model"] = model_name
        persist_assistant_selection(provider.id, model_name)
        console.print(
            f"{SUCCESS} Switched to provider: {provider.alias}"
            + (f" (model: {model_name})" if model_name else "")
        )

    else:
        console.print(f"Unknown provider command: {cmd}")


def _handle_assistant(args: list[str], shell_state: dict) -> None:
    """Configure the default assistant (the agent used for direct chat).

    This is also the session agent: whatever is chosen here is persisted and
    reused on the next launch.
    """
    if not args:
        cmd = "show"
        rest: list[str] = []
    else:
        cmd, rest = _parse_args(args)

    if cmd == "show":
        provider, model = get_assistant_selection()
        if not provider:
            console.print(f"{WARN} No assistant configured yet.")
            return
        console.print(
            f"{BEE} [bold]assistant[/bold] — provider: [cyan]{provider.alias}[/cyan] "
            f"({provider.provider_type}), model: [cyan]{model or 'none'}[/cyan]"
        )
        return

    if cmd == "use":
        if not rest:
            console.print("Usage: /assistant use <provider-alias|number> [model]")
            return
        provider = _resolve_provider(rest[0])
        if not provider:
            console.print(f"{ERROR} Provider {rest[0]!r} not found")
            return
        model_name = rest[1] if len(rest) > 1 else None
        if not model_name:
            model_name = provider.default_model
        shell_state["provider"] = provider
        shell_state["default_model"] = model_name
        persist_assistant_selection(provider.id, model_name)
        console.print(
            f"{SUCCESS} Assistant now uses {provider.alias}"
            + (f" / {model_name}" if model_name else " (no model set)")
        )
        return

    if cmd == "model":
        provider = shell_state.get("provider") or get_assistant_selection()[0]
        if not provider:
            console.print(f"{WARN} No provider selected. Use /assistant use <provider> first.")
            return

        model_name = rest[0] if rest else None
        if not model_name:
            from hobees.core.model_discovery import fetch_provider_models

            models = fetch_provider_models(provider, refresh_cache=False)
            if not models:
                console.print(f"{WARN} No models available for {provider.alias}.")
                model_name = Prompt.ask("Model name", default=shell_state.get("default_model") or provider.default_model or "")
            else:
                console.print(f"\nAvailable models for {provider.alias}:")
                model_name = interactive_model_picker(
                    models, default=shell_state.get("default_model") or provider.default_model
                )

        if not model_name:
            console.print(f"{WARN} Model unchanged.")
            return

        shell_state["provider"] = provider
        shell_state["default_model"] = model_name
        persist_assistant_selection(provider.id, model_name)
        console.print(f"{SUCCESS} Assistant model set to: {model_name}")
        return

    console.print("[bold]Assistant commands:[/bold] show, use <provider> [model], model [name]")


def _handle_bee(args: list[str], shell_state: dict) -> None:
    if not args:
        console.print(f"[bold]Bee commands:[/bold] create, list, update, delete, thinking")
        return

    cmd, rest = _parse_args(args)

    provider = shell_state.get("provider")
    if not provider and cmd != "list":
        console.print(f"{WARN} No provider selected. Use /provider add first.")
        return

    if cmd == "create":
        name = Prompt.ask("Bee name")
        role = Prompt.ask("Role description")
        system_prompt = Prompt.ask("System prompt")
        with session_scope() as session:
            providers = session.query(LLMProvider).all()
        if not providers:
            console.print(f"{WARN} No providers registered — run '/provider add' first.")
            return
        provider_choices = [p.alias for p in providers]
        provider_alias = Prompt.ask("Provider", choices=provider_choices)
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=provider_alias).first()
        model_name = Prompt.ask("Model name", default=provider.default_model if provider else "")
        temperature = float(Prompt.ask("Temperature (0.0-1.0)", default="0.7"))
        tool_names = Prompt.ask("Comma-separated tool names", default="")
        thinking = Prompt.ask("Thinking level", choices=["off", "low", "medium", "high"], default="off")
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=provider_alias).first()
        cmd_bee_create(name, role, system_prompt, provider.id, model_name, temperature, tool_names, thinking)

    elif cmd == "list":
        cmd_bee_list()

    elif cmd == "update":
        name = Prompt.ask("Bee name")
        provider_id = None
        with session_scope() as session:
            providers = session.query(LLMProvider).all()
        if providers:
            provider_alias = Prompt.ask("New provider (or Enter to skip)", choices=[p.alias for p in providers] + [""], default="", show_choices=False)
            if provider_alias:
                with session_scope() as session:
                    provider = session.query(LLMProvider).filter_by(alias=provider_alias).first()
                if provider:
                    provider_id = provider.id
        model_name = Prompt.ask("New model (or Enter to skip)", default="", show_default=False) or None
        temp_str = Prompt.ask("New temperature (or Enter to skip)", default="", show_default=False)
        temperature = float(temp_str) if temp_str else None
        thinking = Prompt.ask("New thinking level (or Enter to skip)", choices=["off", "low", "medium", "high", ""], default="", show_choices=False) or None
        system_prompt = Prompt.ask("New system prompt (or Enter to skip)", default="", show_default=False) or None
        role = Prompt.ask("New role description (or Enter to skip)", default="", show_default=False) or None
        tool_names = Prompt.ask("New tool names (or Enter to skip)", default="", show_default=False) or ""
        cmd_bee_update(name, provider_id, model_name, temperature, thinking, system_prompt, role, tool_names)

    elif cmd == "delete":
        name = Prompt.ask("Bee name to delete")
        cmd_bee_delete(name)

    elif cmd == "thinking":
        name = Prompt.ask("Bee name")
        level = Prompt.ask("Thinking level", choices=["off", "low", "medium", "high"])
        cmd_bee_thinking(name, level)

    else:
        console.print(f"Unknown bee command: {cmd}")


def _handle_hive(args: list[str], shell_state: dict) -> None:
    if not args:
        console.print(f"[bold]Hive commands:[/bold] create, add-bee, remove-bee, list, remove, use, auto, thinking")
        return

    cmd, rest = _parse_args(args)

    provider = shell_state.get("provider")
    if not provider and cmd not in ("list", "remove", "use", "auto"):
        console.print(f"{WARN} No provider selected. Use /provider add first.")
        return

    if cmd == "create":
        name = Prompt.ask("Hive name")
        goal = Prompt.ask("Goal description (optional)", default="")
        with session_scope() as session:
            providers = session.query(LLMProvider).all()
        if not providers:
            console.print(f"{WARN} No providers registered — run '/provider add' first.")
            return
        provider_choices = [p.alias for p in providers]
        provider_alias = Prompt.ask("Supervisor provider", choices=provider_choices)
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=provider_alias).first()
        supervisor_model = Prompt.ask("Supervisor model", default=provider.default_model if provider else "gpt-4o-mini")
        supervisor_prompt = Prompt.ask("Supervisor prompt (optional)", default="")
        is_dynamic = Prompt.ask("Dynamic hive?", choices=["y", "n"], default="n") == "y"
        thinking = Prompt.ask("Supervisor thinking level", choices=["off", "low", "medium", "high"], default="medium")
        
        # Ask about creating a subproject directory
        project_root = shell_state.get("project_root")
        project_path = None
        if project_root:
            create_subproject = Prompt.ask("Create subproject directory under project root?", choices=["y", "n"], default="y") == "y"
            if create_subproject:
                subproject_name = Prompt.ask("Subproject directory name", default=name)
                from pathlib import Path
                project_path = str(Path(project_root) / subproject_name)
        
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=provider_alias).first()
        cmd_hive_create(name, goal or None, provider.id, supervisor_model, supervisor_prompt or None, is_dynamic, thinking, project_path)

    elif cmd == "add-bee":
        hive_name = Prompt.ask("Hive name")
        bee_name = Prompt.ask("Bee name")
        cmd_hive_add_bee(hive_name, bee_name)

    elif cmd == "remove-bee":
        hive_name = Prompt.ask("Hive name")
        bee_name = Prompt.ask("Bee name")
        cmd_hive_remove_bee(hive_name, bee_name)

    elif cmd == "list":
        cmd_hive_list()

    elif cmd == "remove":
        cmd_hive_remove_interactive(" ".join(rest) if rest else None)

    elif cmd == "use":
        if not rest:
            hive_name = Prompt.ask("Hive name")
        else:
            hive_name = rest[0]
        with session_scope() as session:
            hive = session.query(Hive).filter_by(name=hive_name).first()
        if not hive:
            console.print(f"{ERROR} Hive {hive_name!r} not found")
            return
        shell_state["active_hive"] = hive_name
        console.print(f"{SUCCESS} Switched to Hive: {hive_name}")

    elif cmd == "auto":
        shell_state["active_hive"] = None
        console.print(f"{SUCCESS} Switched to Queen auto-mode")

    elif cmd == "thinking":
        hive_name = Prompt.ask("Hive name")
        level = Prompt.ask("Thinking level", choices=["off", "low", "medium", "high"])
        cmd_hive_thinking(hive_name, level)

    elif cmd == "artifacts":
        target = rest[0] if rest else shell_state.get("active_hive")
        if not target:
            console.print(f"{WARN} Specify a hive name or switch to one first with '/hive use <name>'")
            return
        from hobees.cli.hive_cmd import get_hive_artifacts_dir
        art_dir = get_hive_artifacts_dir(target)
        if not art_dir.exists():
            console.print(f"{WARN} Artifacts directory for '{target}' does not exist: {art_dir}")
            return
        console.print(f"\n📁 [bold]Artifacts for Hive: {target}[/bold] ({art_dir.resolve()})")
        files = list(art_dir.rglob("*"))
        if not files:
            console.print("  (No artifacts generated yet)")
        for f in sorted(files):
            if f.is_file():
                rel = f.relative_to(art_dir)
                size = f.stat().st_size
                console.print(f"  • {rel} [dim]({size:,} bytes)[/dim]")

    elif cmd == "trace":
        target = rest[0] if rest else shell_state.get("active_hive")
        if not target:
            console.print(f"{WARN} Specify a hive name or switch to one first with '/hive use <name>'")
            return
        from hobees.cli.hive_cmd import get_hive_artifacts_dir
        traces_dir = get_hive_artifacts_dir(target) / "traces"
        if not traces_dir.exists():
            console.print(f"{WARN} No trace directory found for '{target}'")
            return
        trace_files = sorted(traces_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not trace_files:
            console.print(f"{WARN} No trace logs found for '{target}'")
            return
        latest = trace_files[0]
        console.print(f"\n📜 [bold]Latest Trace Log for {target}[/bold] ({latest.name})")
        with open(latest, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                    t = ev.get("timestamp", "").split("T")[-1][:8]
                    etype = ev.get("event_type")
                    src = ev.get("source")
                    tgt = ev.get("target") or ""
                    payload = ev.get("payload", {})
                    if etype == "THOUGHT":
                        continue
                    detail = (
                        payload.get("subtask_preview")
                        or payload.get("tool_name")
                        or payload.get("content_preview")
                        or ""
                    )
                    console.print(f"  [dim]{t}[/dim] [[bold cyan]{etype}[/bold cyan]] {src} -> {tgt}: {str(detail)[:75]}")
                except Exception:
                    console.print(f"  {line.strip()[:100]}")

    else:
        console.print(f"Unknown hive command: {cmd}")


def _handle_goal(args: list[str], provider: LLMProvider, db_url: str, shell_state: dict) -> None:
    """Run a goal through the Queen (auto-mode)."""
    if not args:
        console.print("No goal provided.")
        return

    if not provider:
        console.print(f"{WARN} No provider selected. Use /provider add first.")
        return

    goal = " ".join(args)
    bee_names = Prompt.ask("Comma-separated bee names (or press Enter for auto-select)", default="")

    with session_scope() as session:
        bees = session.query(Bee).all()

    if not bees:
        console.print(f"{WARN} No Worker Bees registered — run '/bee create' first.")
        return

    chosen = []
    if bee_names.strip():
        wanted = {n.strip() for n in bee_names.split(",") if n.strip()}
        chosen = [b for b in bees if b.name in wanted]
        if not chosen:
            console.print(f"{WARN} No bees found: {bee_names}")
            return

    hive_id: int | None = None
    run_id: int | None = None
    thread_id = uuid.uuid4().hex
    shell_state["thread_id"] = thread_id
    try:
        with session_scope() as session:
            hive = Hive(
                name=f"auto-{uuid.uuid4().hex[:8]}",
                goal_description=goal,
                supervisor_provider_id=provider.id,
                supervisor_model_name=provider.default_model,
                supervisor_prompt=None,
                is_dynamic=True,
            )
            session.add(hive)
            session.flush()
            hive_id = hive.id
            for bee in chosen:
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
        with session_scope() as session:
            providers = {p.id: p for p in session.query(LLMProvider).all()}

        thinking_override = shell_state.get("thinking_override", "medium")
        queen = build_queen(provider, provider.default_model, db_url, thread_id, thinking_override)

        with hive_app(hive, chosen, providers, db_url, thread_id, run_id, thinking_override) as app:
            result = app.invoke(
                {"messages": [("user", goal)]},
                config={"configurable": {"thread_id": thread_id}},
            )
        output = str(result)
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
        from hobees.core.memory_manager import extract_run_memories

        extract_run_memories(
            goal=goal,
            output=Queen._extract_output(result),
            provider=provider,
            model_name=provider.default_model,
            hive_name=hive.name,
            source_thread_id=thread_id,
            allow_hive_facts=False,
        )
        from hobees.core.skill_harvester import harvest_completed_run

        harvest_completed_run(run_id)
        console.print(f"{SUCCESS} Hive completed: {output}")

        _show_telemetry_footer(thread_id)
        _check_skill_draft(run_id)

    except Exception as exc:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = "failed"
                run.completed_at = None
        console.print(f"{ERROR} Hive failed: {exc}")


def _handle_usage(args: list[str]) -> None:
    if not args:
        console.print("[bold]Usage commands:[/bold] all, bee, hive, provider, day")
        return

    window = args[0] if args else "all"
    from hobees.db.analytics import summary as get_summary
    summary = get_summary(window=window)
    if not summary:
        console.print(f"No usage data for {window}.")
        return
    console.print(f"[bold]Usage ({window}):[/bold]")
    for row in summary:
        key = list(row.keys())[0]
        console.print(f"  • {key}: events={row.get('events', 0)}, input_tokens={row.get('input_tokens', 0)}, output_tokens={row.get('output_tokens', 0)}, cost={row.get('estimated_cost_usd', 0)}")


def _handle_thinking(args: list[str], shell_state: dict) -> None:
    levels = ("off", "low", "medium", "high", "auto")
    if not args:
        current = shell_state.get("thinking_override", "auto")
        console.print(f"[bold]Session thinking override:[/bold] {current}")
        console.print(f"  Valid levels: {' '.join(levels)}")
        return
    if args[0] not in levels:
        console.print(f"[bold]Invalid thinking level: {args[0]}[/bold]")
        console.print(f"  Valid levels: {' '.join(levels)}")
        return
    shell_state["thinking_override"] = args[0]
    console.print(f"{SUCCESS} Session thinking level set to '{args[0]}'")


def _handle_compact(provider: LLMProvider, db_url: str, shell_state: dict) -> None:
    """Compress the active thread's message history."""
    thread_id = shell_state.get("thread_id")
    if not thread_id:
        console.print(f"{WARN} No active thread to compact.")
        return

    from hobees.core.context_manager import compact_messages
    from hobees.db.session import session_scope
    from hobees.db.models import Run

    saver, checkpoint_connection = _get_checkpointer(db_url)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        checkpoint_tuple = saver.get_tuple(config)
    except Exception:
        checkpoint_tuple = None
    finally:
        if checkpoint_connection:
            checkpoint_connection.close()

    if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
        console.print(f"{WARN} No saved checkpoint found for thread {thread_id[:8]}... to compact.")
        return

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    messages = channel_values.get("messages", [])
    if not messages:
        console.print(f"{WARN} Thread {thread_id[:8]}... has empty message history.")
        return

    if len(messages) <= 2:
        console.print(f"{WARN} Message history is very short ({len(messages)} messages). Compaction not needed.")
        return

    recent = messages[-2:]
    older = messages[:-2]

    summary_lines = []
    for m in older:
        role = getattr(m, "name", None) or type(m).__name__
        content = getattr(m, "content", "")
        summary_lines.append(f"- {role}: {str(content)[:300]}")
    summary = "Previous context summary:\n" + "\n".join(summary_lines)

    shell_state["running_summary"] = summary

    # Update database Run record
    with session_scope() as session:
        run = session.query(Run).filter_by(thread_id=thread_id).first()
        if run:
            run.compacted_count = (run.compacted_count or 0) + 1

    console.print(f"{COMPACT} [bold]Context compacted[/bold] — {len(older)} messages folded into running_summary ({len(recent)} messages retained).")
    preview = summary.replace("\n", " ")[:120]
    console.print(f"  [dim]Summary preview: {preview}...[/dim]")


def _handle_memory(args: list[str]) -> None:
    if not args:
        console.print(f"[bold]Memory commands:[/bold] list, add <key> '<content>', forget <key>, show <key>")
        return

    cmd, rest = _parse_args(args)

    if cmd == "list":
        namespace = rest[0] if rest else None
        cmd_memory_list(namespace)

    elif cmd == "add":
        if len(rest) < 2:
            console.print("Usage: /memory add <namespace> <key> '<content>'")
            return
        namespace = rest[0]
        key = rest[1]
        content = " ".join(rest[2:])
        cmd_memory_add(key, content, namespace)

    elif cmd == "forget":
        if not rest:
            console.print("Usage: /memory forget <namespace> <key>")
            return
        namespace = rest[0]
        key = rest[1]
        cmd_memory_forget(key, namespace)

    elif cmd == "show":
        if not rest:
            console.print("Usage: /memory show <namespace> <key>")
            return
        namespace = rest[0]
        key = rest[1]
        cmd_memory_show(key, namespace)

    else:
        console.print("[bold]Memory usage:[/bold] list, add <namespace> <key> '<content>', forget <namespace> <key>, show <namespace> <key>")


def _handle_skill(args: list[str]) -> None:
    if not args:
        console.print("[bold]Skill commands:[/bold] list, show <name>, create, save-last, assign <skill> <bee>, unassign <skill> <bee>, sync")
        return

    cmd, rest = _parse_args(args)

    if cmd == "list":
        cmd_skill_list()

    elif cmd == "show":
        if not rest:
            console.print("Usage: /skill show <name>")
            return
        cmd_skill_show(" ".join(rest))

    elif cmd == "create":
        name = Prompt.ask("Skill name (kebab-case)", default="")
        description = Prompt.ask("Description", default="")
        console.print("Enter instructions (Markdown). End with Ctrl+D / Ctrl+Z:")
        import sys
        instructions = sys.stdin.read()
        tags = Prompt.ask("Tags (comma-separated)", default="")
        cmd_skill_create(name or None, description or None, instructions, tags)

    elif cmd == "save-last":
        cmd_skill_save_last()

    elif cmd == "assign":
        if len(rest) < 2:
            console.print("Usage: /skill assign <skill_name> <bee_name>")
            return
        cmd_skill_assign(rest[0], rest[1])

    elif cmd == "unassign":
        if len(rest) < 2:
            console.print("Usage: /skill unassign <skill_name> <bee_name>")
            return
        cmd_skill_unassign(rest[0], rest[1])

    elif cmd == "sync":
        cmd_skill_sync()

    else:
        console.print("[bold]Skill usage:[/bold] list, show <name>, create, save-last, assign <skill> <bee>, unassign <skill> <bee>, sync")


def _handle_session(args: list[str], shell_state: dict) -> None:
    if not args:
        console.print("[bold]Session commands:[/bold] save <name>, load <name>, list, delete <name>")
        return

    cmd, rest = _parse_args(args)

    if cmd == "save":
        if not rest:
            console.print("Usage: /session save <name>")
            return
        name = rest[0]
        state = _capture_session_state(shell_state.get("active_hive"), shell_state.get("thread_id"))
        _save_session(name, state)
        console.print(f"{SUCCESS} Session '{name}' saved.")

    elif cmd == "load":
        if not rest:
            console.print("Usage: /session load <name>")
            return
        name = rest[0]
        data = _load_session(name)
        if not data:
            console.print(f"{ERROR} Session '{name}' not found")
            return
        shell_state["active_hive"] = data.get("active_hive")
        shell_state["thread_id"] = data.get("thread_id")
        console.print(f"{SUCCESS} Session '{name}' loaded. Active hive: {shell_state['active_hive'] or 'Queen auto-mode'}")

    elif cmd == "list":
        sessions = _list_sessions()
        if not sessions:
            console.print("No saved sessions.")
            return
        table = Table(title="Saved Sessions")
        table.add_column("name", style="cyan")
        table.add_column("active_hive")
        table.add_column("thread_id")
        for s in sessions:
            data = _load_session(s)
            if data:
                active_hive = data.get("active_hive") or "-"
                thread_id = data.get("thread_id") or "-"
                table.add_row(s, active_hive, thread_id[:8] + "...")
        console.print(table)

    elif cmd == "delete":
        if not rest:
            console.print("Usage: /session delete <name>")
            return
        name = rest[0]
        if _delete_session(name):
            console.print(f"{SUCCESS} Session '{name}' deleted.")
        else:
            console.print(f"{ERROR} Session '{name}' not found.")

    else:
        console.print("[bold]Session usage:[/bold] save <name>, load <name>, list, delete <name>")


def _handle_chat(args: list[str], provider: LLMProvider | None, db_url: str, shell_state: dict) -> None:
    """Chat directly with a Bee or Hive."""
    if not provider:
        console.print(f"{WARN} No provider selected. Use /provider add first.")
        return

    if not args:
        console.print("[bold]Chat commands:[/bold] bee <name>, hive <name>, list")
        return

    cmd, rest = _parse_args(args)

    if cmd == "list":
        with session_scope() as session:
            bees = session.query(Bee).all()
            hives = session.query(Hive).options(
                joinedload(Hive.memberships).joinedload(HiveMembership.bee)
            ).all()
        if bees:
            console.print("[bold]Available Bees:[/bold]")
            for b in bees:
                console.print(f"  {BEE} {b.name}: {b.role_description} ({b.provider.alias}/{b.model_name})")
        if hives:
            console.print("[bold]Available Hives:[/bold]")
            for h in hives:
                members = ", ".join(m.bee.name for m in h.memberships) or "(none)"
                console.print(f"  {HIVE} {h.name}: {h.supervisor_provider.alias}/{h.supervisor_model_name} - bees: {members}")
        return

    if cmd == "bee":
        if not rest:
            console.print("Usage: /chat bee <name>")
            return
        import asyncio
        asyncio.run(_chat_with_bee(rest[0], provider, db_url, shell_state))
        return

    if cmd == "hive":
        if not rest:
            console.print("Usage: /chat hive <name>")
            return
        import asyncio
        asyncio.run(_chat_with_hive(rest[0], provider, db_url, shell_state))
        return

    console.print("[bold]Chat usage:[/bold] /chat bee <name>, /chat hive <name>, /chat list")


def _panel_tail(text: str, lines: int = 8, width: int = 400) -> str:
    """Last few width-wrapped lines of a growing buffer.

    The thoughts panel has a fixed height, so long reasoning has to be clipped
    from the top while it streams.
    """
    rows: list[str] = []
    for line in text.splitlines() or [""]:
        while len(line) > width:
            rows.append(line[:width])
            line = line[width:]
        rows.append(line)
    return "\n".join(rows[-lines:])


async def _chat_with_bee(bee_name: str, provider: LLMProvider, db_url: str, shell_state: dict) -> None:
    """Chat directly with a single Bee - streaming with thoughts panel."""
    from hobees.core.llm_factory import get_chat_model
    from hobees.core.tool_registry import get_tools
    from hobees.db.session import session_scope
    from hobees.db.models import Bee
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Group
    import time

    with session_scope() as session:
        bee = session.query(Bee).filter_by(name=bee_name).first()
    if not bee:
        console.print(f"{ERROR} Bee {bee_name!r} not found")
        return

    bee_provider = None
    with session_scope() as session:
        bee_row = session.query(Bee).filter_by(name=bee_name).first()
        if bee_row:
            bee_provider = session.query(type(provider)).filter_by(id=bee_row.provider_id).first()

    if not bee_provider:
        console.print(f"{ERROR} Could not find provider for bee {bee_name!r}")
        return

    thread_id = uuid.uuid4().hex
    shell_state["thread_id"] = thread_id

    thinking_override = shell_state.get("thinking_override", "auto")
    if thinking_override == "auto":
        thinking_level = bee.thinking_level
    else:
        thinking_level = thinking_override

    # Set thread context for tool truncation and project root
    from hobees.core.tool_registry import set_thread_context
    project_root = shell_state.get("project_root")
    set_thread_context(thread_id, project_root=project_root)

    from hobees.core.telemetry import build_telemetry_handler
    _telemetry = build_telemetry_handler(
        bee_provider, bee_name=bee.name, model_name=bee.model_name, thread_id=thread_id
    )
    model = get_chat_model(
        bee_provider,
        bee.model_name,
        bee.temperature,
        callbacks=[_telemetry],
        thinking_level=thinking_level,
    )
    tools = get_tools(bee.tool_names)

    from hobees.core.memory_manager import extract_namespaces, build_memory_block
    from hobees.core.tool_registry import get_skill_metadata

    memory_namespaces = extract_namespaces(global_=True, bee_name=bee_name)
    memory_block = build_memory_block(memory_namespaces)

    bee_skills = [
        {"name": s.name, "description": s.description}
        for s in get_skill_metadata()
        if s.name in [skill.name for skill in bee.skills]
    ]

    system_prompt_parts = []
    if bee.system_prompt:
        system_prompt_parts.append(bee.system_prompt)
    if memory_block:
        system_prompt_parts.append(memory_block)
    if bee_skills:
        skills_text = "\n".join(f"- {s['name']}: {s['description']}" for s in bee_skills)
        system_prompt_parts.append(f"## Available Skills (use load_skill to read)\n{skills_text}")

    full_system_prompt = "\n\n".join(system_prompt_parts) if system_prompt_parts else None

    from langchain.agents import create_agent

    saver, checkpoint_connection = _get_checkpointer(db_url)

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=full_system_prompt,
        name=bee.name,
        checkpointer=saver,
    )

    console.print(f"[bold]Chatting with {BEE} {bee.name}[/bold] (type 'exit' to return)")

    actions_buffer: list[str] = []

    def make_layout(view: dict):
        thoughts_text = Text()
        for action in actions_buffer[-3:]:
            thoughts_text.append(action + "\n", style="dim cyan")
        thinking = view.get("thinking", "")
        if thinking:
            thoughts_text.append(_panel_tail(thinking, lines=4) + "\n", style="dim")
        elif not actions_buffer and not view.get("done"):
            thoughts_text.append("Waiting for bee...\n", style="dim")
        thoughts_panel = Panel(thoughts_text, title="🧠 Bee Thoughts & Actions", border_style="yellow", height=6)
        output_text = Text(view.get("answer", ""), style="white")
        output_panel = Panel(output_text, title="💬 Response", border_style="green")
        return Group(thoughts_panel, output_panel)
    
    console.print()
    
    try:
        view: dict = {"thinking": "", "answer": ""}
        with Live(make_layout(view), console=console, refresh_per_second=20, transient=False) as live:
            while True:
                try:
                    user_input = console.input(f"{BEE} {bee.name} > ")
                except (KeyboardInterrupt, EOFError):
                    console.print("\nReturning to main shell.")
                    break

                if user_input.strip().lower() in ("exit", "quit"):
                    break
                if not user_input.strip():
                    continue

                actions_buffer.clear()
                view["thinking"] = ""
                view["answer"] = ""
                view["done"] = False

                # Token-level streaming: render thinking and the answer as they
                # are generated instead of after the whole turn completes.
                # Start escape key listener
                listener_task = asyncio.create_task(_stdin_escape_listener(cancel_flag))
                try:
                    streamer = DeltaStreamer()
                    async for _item in agent.astream(
                        {"messages": [("user", user_input)]},
                        config={"configurable": {"thread_id": thread_id}},
                        stream_mode="messages",
                    ):
                        if cancel_flag.get("cancelled"):
                            console.print("\n[dim]Cancelled.[/dim]")
                            break
                        for _kind, _text in streamer.feed(_item):
                            if _kind == "action":
                                actions_buffer.append(_text)
                            else:
                                _slot = "answer" if _kind == "assistant" else _kind
                                view[_slot] = view.get(_slot, "") + _text
                        live.update(make_layout(view))

                    full_response = streamer.text
                    view["done"] = True
                    live.update(make_layout(view))
                    await asyncio.sleep(0.2)
                finally:
                    listener_task.cancel()
                    try:
                        await listener_task
                    except asyncio.CancelledError:
                        pass

                from hobees.db.analytics import run_thread_usage
                usage = run_thread_usage(thread_id)
                if usage:
                    events = usage.get('events', 0) or 0
                    in_toks = usage.get('input_tokens', 0) or 0
                    out_toks = usage.get('output_tokens', 0) or 0
                    cost = usage.get('estimated_cost_usd', 0) or 0.0
                    console.print(f"  tokens: {in_toks:,} in / {out_toks:,} out • ${cost:.4f} • {events} calls")
    except Exception as exc:
        console.print(f"{ERROR} Error: {exc}")
    finally:
        if checkpoint_connection:
            checkpoint_connection.close()


async def _chat_with_hive(
    hive_name: str,
    provider: LLMProvider,
    db_url: str,
    shell_state: dict,
    initial_input: str | None = None,
) -> None:
    """Chat with a Hive (uses the full supervisor + workers) - streaming with thoughts panel."""
    from hobees.core.hive_builder import hive_app_async
    from hobees.db.session import session_scope
    from hobees.db.models import Hive, Bee, HiveMembership, LLMProvider, Run
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Group
    import time

    with session_scope() as session:
        hive = session.query(Hive).filter_by(name=hive_name).first()
    if not hive:
        console.print(f"{ERROR} Hive {hive_name!r} not found")
        return

    with session_scope() as session:
        memberships = session.query(HiveMembership).filter_by(hive_id=hive.id).all()
        bee_ids = [m.bee_id for m in memberships]
        bees = session.query(Bee).filter(Bee.id.in_(bee_ids)).all() if bee_ids else []
        providers = {p.id: p for p in session.query(LLMProvider).all()}

    if not bees:
        console.print(f"{WARN} Hive {hive_name!r} has no bees assigned")
        return

    thread_id = uuid.uuid4().hex
    shell_state["thread_id"] = thread_id
    user_messages: list[str] = []
    with session_scope() as session:
        run = Run(
            thread_id=thread_id,
            hive_id=hive.id,
            mode="hive",
            goal=initial_input or f"Interactive chat with Hive {hive.name}",
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id

    thinking_override = shell_state.get("thinking_override", "auto")

    # Set thread context for tool truncation and project root
    from hobees.core.tool_registry import set_thread_context
    project_root = shell_state.get("project_root")
    if hive.project_path:
        project_root = hive.project_path
    set_thread_context(thread_id, project_root=project_root)

    console.print(f"[bold]Chatting with {HIVE} {hive.name}[/bold] (type 'exit' to return)")

    async with hive_app_async(
        hive, bees, providers, db_url, thread_id, run_id, thinking_override
    ) as app:
        actions_buffer: list[str] = []

        def make_layout(view: dict):
            thoughts_text = Text()
            for action in actions_buffer[-3:]:
                thoughts_text.append(action + "\n", style="dim cyan")
            thinking = view.get("thinking", "")
            if thinking:
                thoughts_text.append(_panel_tail(thinking, lines=4) + "\n", style="dim")
            elif not actions_buffer and not view.get("done"):
                thoughts_text.append("Waiting for hive...\n", style="dim")
            thoughts_panel = Panel(thoughts_text, title="🧠 Hive Thoughts & Actions", border_style="blue", height=6)
            output_text = Text(view.get("answer", ""), style="white")
            output_panel = Panel(output_text, title="💬 Response", border_style="green")
            return Group(thoughts_panel, output_panel)

        console.print()

        view: dict = {"thinking": "", "answer": ""}
        full_response = ""

        with Live(make_layout(view), console=console, refresh_per_second=20, transient=False) as live:
            while True:
                # User input loop
                try:
                    if initial_input is not None:
                        user_input = initial_input
                        initial_input = None
                    else:
                        user_input = console.input(f"{HIVE} {hive.name} > ")
                except (KeyboardInterrupt, EOFError):
                    console.print("\nReturning to main shell.")
                    break

                if user_input.strip().lower() in ("exit", "quit"):
                    break
                if not user_input.strip():
                    continue

                user_messages.append(user_input)
                actions_buffer.clear()
                view["thinking"] = ""
                view["answer"] = ""
                view["done"] = False

                # Start escape key listener
                listener_task = asyncio.create_task(_stdin_escape_listener(cancel_flag))
                stream_aiter = None
                
                # Inner try wraps the streaming and cleanup
                try:
                    # Token-level streaming so thinking/answer appear live.
                    streamer = DeltaStreamer()
                    stream_aiter = app.astream(
                        {"messages": [("user", user_input)]},
                        config={"configurable": {"thread_id": thread_id}},
                        stream_mode="messages",
                    )
                    async for _item in stream_aiter:
                        if cancel_flag.get("cancelled"):
                            console.print("\n[dim]Cancelled.[/dim]")
                            break
                        for _kind, _text in streamer.feed(_item):
                            if _kind == "action":
                                actions_buffer.append(_text)
                            else:
                                _slot = "answer" if _kind == "assistant" else _kind
                                view[_slot] = view.get(_slot, "") + _text
                        live.update(make_layout(view))
                    full_response = streamer.text
                except Exception as exc:
                    full_response = f"{ERROR} Error: {exc}"
                finally:
                    view["done"] = True
                    live.update(make_layout(view))
                    time.sleep(0.2)
                    
                    # Properly close the async generator to avoid pending task warnings
                    if stream_aiter is not None:
                        try:
                            await stream_aiter.aclose()
                        except Exception:
                            pass
                    
                    # Cleanup listener task
                    listener_task.cancel()
                    try:
                        await listener_task
                    except asyncio.CancelledError:
                        pass

    completed_at = datetime.now(timezone.utc)
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run:
            if user_messages:
                run.goal = "\n".join(user_messages)
            run.status = "completed"
            run.completed_at = completed_at

    from hobees.core.skill_harvester import harvest_completed_run

    if harvest_completed_run(run_id):
        _check_skill_draft(run_id)


def _handle_cancel(shell_state: dict) -> None:
    """Cancel the current running task."""
    shell_state["cancel_task"] = True
    console.print("[dim]Cancelling current task...[/dim]")


def _handle_help(args: list[str]) -> None:
    """Show help for available slash commands."""
    console.print("[bold]Available slash commands:[/bold]")
    for cmd, (desc, subcmds) in sorted(_COMMANDS.items()):
        sub = f" ({', '.join(subcmds)})" if subcmds else ""
        console.print(f"  /{cmd:<16} {desc}{sub}")
    console.print("[dim]Type /help for this list again.[/dim]")


def _show_telemetry_footer(thread_id: str) -> None:
    """Show the telemetry footer after a run."""
    from hobees.db.analytics import run_thread_usage
    usage = run_thread_usage(thread_id)
    if usage:
        events = usage.get('events', 0) or 0
        in_toks = usage.get('input_tokens', 0) or 0
        out_toks = usage.get('output_tokens', 0) or 0
        cost = usage.get('estimated_cost_usd', 0) or 0.0
        console.print(
            f"Run: tokens: {in_toks:,} in / {out_toks:,} out • ${cost:.4f} • {events} LLM calls"
        )


def _check_skill_draft(run_id: int) -> None:
    """Check if a skill draft was generated and prompt the user."""
    from hobees.db.models import Run
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run and run.suggested_skill_draft:
            draft = run.suggested_skill_draft
            name = draft.get('name', 'unnamed-skill')
            desc = draft.get('description', '')
            console.print(f"\n{SKILL} [bold]Skill Idea Detected:[/bold] {name}")
            console.print(f"   {desc}")
            console.print("   Save to Skill Library? [y/N/edit] (or run /skill save-last later)")
            choice = Prompt.ask("Choice", choices=["y", "n", "e"], default="n")
            if choice == "y":
                from hobees.core.skill_harvester import persist_skill
                skill = persist_skill(draft, run.thread_id)
                console.print(f"{SUCCESS} Saved skill '{skill.name}'")
            elif choice == "e":
                draft["description"] = Prompt.ask("Description", default=desc)
                console.print("Enter instructions (Markdown). End with Ctrl+D / Ctrl+Z:")
                import sys
                draft["instructions"] = sys.stdin.read()
                from hobees.core.skill_harvester import persist_skill
                skill = persist_skill(draft, run.thread_id)
                console.print(f"{SUCCESS} Saved skill '{skill.name}'")


# -- Main shell loop ------------------------------------------------------

_PROMPT_SESSION = None


def _get_prompt_session():
    """Lazily build the completer-backed prompt used by the interactive shell."""
    global _PROMPT_SESSION
    if _PROMPT_SESSION is None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import merge_completers
        from prompt_toolkit.key_binding import KeyBindings

        from hobees.cli.completion import (
            FilePathCompleter,
            SlashCommandCompleter,
            add_completion_accept_binding,
        )

        key_bindings = KeyBindings()
        add_completion_accept_binding(key_bindings)

        _PROMPT_SESSION = PromptSession(
            completer=merge_completers(
                [SlashCommandCompleter(_COMMANDS), FilePathCompleter()]
            ),
            complete_while_typing=True,
            reserve_space_for_menu=4,
            key_bindings=key_bindings,
        )
    return _PROMPT_SESSION


def _read_line(prompt_text: str) -> str:
    """Read one line of input, offering ``/`` command completion on a TTY.

    Falls back to a plain ``input()`` when stdin is redirected (pipes, scripts,
    tests), where prompt_toolkit cannot drive the terminal.
    """
    if not sys.stdin.isatty():
        return console.input(prompt_text)
    return _get_prompt_session().prompt(prompt_text)



async def _stdin_escape_listener(cancel_flag: dict) -> None:
    """Listen for Esc key on stdin during streaming using a background thread.

    Spawns a thread to read stdin in raw mode to detect Escape key (\x1b)
    and sets cancel_flag. This runs concurrently with the streaming loop.
    """
    import sys
    import threading
    import termios
    import tty
    import select
    import asyncio

    if not sys.stdin.isatty():
        return

    stop_event = threading.Event()
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    def reader_thread():
        try:
            tty.setcbreak(fd)
            while not stop_event.is_set() and not cancel_flag.get("cancelled"):
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    ch = sys.stdin.read(1)
                    if ch == "\x1b":  # Escape key
                        cancel_flag["cancelled"] = True
                        break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    thread = threading.Thread(target=reader_thread, daemon=True)
    thread.start()
    try:
        while not cancel_flag.get("cancelled"):
            await asyncio.sleep(0.1)
    finally:
        stop_event.set()
        thread.join(timeout=0.5)

def _shell_loop(ctx_obj: dict | None = None, selected_provider: LLMProvider | None = None) -> None:
    """Main shell loop."""
    from hobees.db.session import session_scope, get_engine
    from hobees.db.models import LLMProvider
    from hobees.cli.provider_cmd import interactive_model_picker
    from hobees.core.model_discovery import fetch_provider_models

    # Initialize shell state
    shell_state = {
        "active_hive": None,
        "thread_id": None,
        "thinking_override": "auto",  # auto | off | low | medium | high
        "provider": selected_provider,
        "cancel_task": False,
    }

    # Handle session resume from CLI args
    if ctx_obj:
        if ctx_obj.get("resume_session"):
            name = ctx_obj["resume_session"]
            data = _load_session(name)
            if data:
                shell_state["active_hive"] = data.get("active_hive")
                shell_state["thread_id"] = data.get("thread_id")
                console.print(f"{SUCCESS} Resumed session: {name}")
            else:
                console.print(f"{WARN} Session '{name}' not found, starting fresh.")
        elif ctx_obj.get("new_session_name"):
            console.print(f"{SUCCESS} Starting new session: {ctx_obj['new_session_name']}")
        if ctx_obj.get("active_hive"):
            shell_state["active_hive"] = ctx_obj["active_hive"]
            console.print(f"{HIVE} [bold]Locked to Hive:[/bold] {ctx_obj['active_hive']}")

    # -- Setup -------------------------------------------------------------
    with session_scope() as session:
        engine = get_engine()
        db_url = engine.url
        
        # Capture current working directory as project root
        from pathlib import Path
        project_root = str(Path.cwd().resolve())
        shell_state["project_root"] = project_root
        
        # Get all providers
        all_providers = session.query(LLMProvider).all()
        
    # Determine the session agent (provider + model) to use.
    #
    # The default assistant bee owns this choice: whatever the user picked last
    # time is what we start with, so a restart never re-asks for a model. We
    # only prompt when there is no usable assistant configuration yet.
    provider = selected_provider
    assistant_provider, assistant_model = get_assistant_selection()

    if provider is None and assistant_provider is not None:
        # Resume the assistant's saved provider/model silently.
        provider = assistant_provider
        shell_state["default_model"] = assistant_model
    elif provider is None:
        if not all_providers:
            # No providers at all - allow user to add in shell from scratch
            provider = None
        elif len(all_providers) == 1:
            provider = all_providers[0]
        else:
            console.print(Panel.fit(
                f"[bold]{APP} hobees Interactive Shell[/bold]\n"
                f"No default assistant configured yet. Please select its provider:",
                border_style="yellow",
            ))
            for i, p in enumerate(all_providers, 1):
                console.print(f"  [cyan]({i})[/cyan] {p.alias} ({p.provider_type}) - default: {p.default_model or 'none'}")

            choice = Prompt.ask("Select provider", choices=[str(i) for i in range(1, len(all_providers) + 1)])
            provider = all_providers[int(choice) - 1]

    if provider is not None and not shell_state.get("default_model"):
        # Keep the assistant's model when it belongs to this provider,
        # otherwise fall back to (or ask for) the provider's model.
        if assistant_model and provider.id == getattr(assistant_provider, "id", None):
            shell_state["default_model"] = assistant_model
        elif provider.default_model:
            shell_state["default_model"] = provider.default_model
        else:
            models = fetch_provider_models(provider, refresh_cache=False)
            if models:
                console.print(f"\nAvailable models for {provider.alias}:")
                selected_model = interactive_model_picker(models, default=None)
                if selected_model:
                    shell_state["default_model"] = selected_model
    
    if provider:
        with session_scope() as session:
            # Refresh provider from session
            provider = session.query(LLMProvider).filter_by(id=provider.id).first()

        # Create default assistant bee if none exist, then make the session's
        # provider/model the assistant's persisted selection.
        _ensure_default_assistant(provider, db_url)
        session_model = shell_state.get("default_model") or provider.default_model
        persist_assistant_selection(provider.id, session_model)
        if session_model:
            shell_state["default_model"] = session_model

        project_root = shell_state.get("project_root", "unknown")
        console.print(Panel.fit(
            f"[bold]{APP} hobees Interactive Shell[/bold]\n"
            f"Provider: [cyan]{provider.alias}[/cyan] ({provider.provider_type})\n"
            f"Model: [cyan]{session_model or 'none'}[/cyan]\n"
            f"Project root: [cyan]{project_root}[/cyan]\n"
            f"Type [cyan]/help[/cyan] for commands, [cyan]/session save <name>[/cyan] to persist state.",
            border_style="yellow",
        ))
    else:
        project_root = shell_state.get("project_root", "unknown")
        console.print(Panel.fit(
            f"[bold]{APP} hobees Interactive Shell[/bold]\n"
            f"No LLM providers configured yet.\n"
            f"Type [cyan]/provider add[/cyan] to add one, or [cyan]/help[/cyan] for commands.\n"
            f"Project root: [cyan]{project_root}[/cyan]",
            border_style="yellow",
        ))

    # Update shell_state with provider
    shell_state["provider"] = provider

    while True:
        try:
            # Build prompt with hive indicator
            active_hive = shell_state.get("active_hive")
            if active_hive:
                prompt_text = f"{APP} (hobees:{active_hive}) > "
            else:
                prompt_text = f"{APP} hobees > "

            # Show thinking indicator
            thinking = shell_state.get("thinking_override", "auto")
            if thinking != "auto":
                prompt_text = f"{THINKING} {thinking} {prompt_text}"

            user_input = _read_line(prompt_text)
        except (KeyboardInterrupt, EOFError):
            console.print("\nExiting shell.")
            break

        if not user_input.strip():
            continue

        parts = user_input.split()
        if not parts:
            continue

        cmd, args = _parse_args(parts)

        # Command handlers are shared with the Typer CLI, where signalling a
        # bad argument means ``raise typer.Exit``. Inside the interactive shell
        # that must only cancel the command -- never tear down the session.
        try:
            should_exit = _dispatch_command(
                cmd, args, user_input, db_url, shell_state
            )
        except (typer.Exit, SystemExit):
            console.print(f"{WARN} Command cancelled.")
            continue
        except KeyboardInterrupt:
            console.print(f"\n{WARN} Interrupted.")
            continue
        except Exception as exc:  # keep the shell alive on any handler bug
            console.print(f"{ERROR} {type(exc).__name__}: {exc}")
            continue

        if should_exit:
            break


def _dispatch_command(
    cmd: str, args: list[str], user_input: str, db_url: str, shell_state: dict
) -> bool:
    """Run one parsed slash command. Returns True when the shell should exit."""
    if cmd in ("help", ""):
        # "" happens for a bare "/", which is how users ask for the list.
        _handle_help(args)
    elif cmd == "provider":
        _handle_provider(args, shell_state)
    elif cmd == "assistant":
        _handle_assistant(args, shell_state)
    elif cmd == "bee":
        _handle_bee(args, shell_state)
    elif cmd == "hive":
        _handle_hive(args, shell_state)
    elif cmd == "chat":
        _handle_chat(args, shell_state.get("provider"), db_url, shell_state)
    elif cmd == "goal":
        _handle_goal(args, shell_state.get("provider"), db_url, shell_state)
    elif cmd == "usage":
        _handle_usage(args)
    elif cmd == "thinking":
        _handle_thinking(args, shell_state)
    elif cmd == "compact":
        _handle_compact(shell_state.get("provider"), db_url, shell_state)
    elif cmd == "memory":
        _handle_memory(args)
    elif cmd == "skill":
        _handle_skill(args)
    elif cmd == "session":
        _handle_session(args, shell_state)
    elif cmd == "cancel":
        _handle_cancel(shell_state)
    elif cmd in ("quit", "exit"):
        console.print("Exiting shell.")
        return True
    else:
        # If input doesn't start with / and we have a provider, treat as chat with assistant
        current_provider = shell_state.get("provider")
        if current_provider and not user_input.startswith("/"):
            import asyncio
            import concurrent.futures

            def run_async_in_thread():
                # Keep chat off this thread's loop so prompt_toolkit can drive
                # the terminal while the model streams.
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    active_hive = shell_state.get("active_hive")
                    if active_hive:
                        return loop.run_until_complete(
                            _chat_with_hive(
                                active_hive,
                                current_provider,
                                db_url,
                                shell_state,
                                initial_input=user_input,
                            )
                        )
                    return loop.run_until_complete(
                        _chat_with_assistant(user_input, current_provider, db_url, shell_state)
                    )
                finally:
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(run_async_in_thread).result()
        else:
            console.print(f"[bold]Unknown command: {cmd}[/bold]")
            console.print("  Type /help to see available commands.")
    return False


async def _chat_with_assistant(user_input: str, provider: LLMProvider, db_url: str, shell_state: dict) -> None:
    """Chat with the default assistant bee - streaming with thoughts panel."""
    from hobees.core.llm_factory import get_chat_model
    from hobees.core.tool_registry import get_tools
    from hobees.db.session import session_scope
    from hobees.db.models import Bee
    from hobees.core.memory_manager import extract_namespaces, build_memory_block
    from hobees.core.tool_registry import get_skill_metadata
    from langchain.agents import create_agent
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Group
    import time

    # Get or create assistant bee
    assistant = _get_or_create_assistant(provider, db_url)
    if not assistant:
        console.print(f"{ERROR} Could not create assistant bee")
        return

    bee_provider = None
    with session_scope() as session:
        bee_provider = session.query(type(provider)).filter_by(id=assistant.provider_id).first()

    if not bee_provider:
        console.print(f"{ERROR} Could not find provider for assistant")
        return

    thread_id = shell_state.get("thread_id") or uuid.uuid4().hex
    shell_state["thread_id"] = thread_id

    # Set thread context for tool truncation and project root
    from hobees.core.tool_registry import set_thread_context
    project_root = shell_state.get("project_root")
    set_thread_context(thread_id, project_root=project_root)

    thinking_override = shell_state.get("thinking_override", "auto")
    if thinking_override == "auto":
        thinking_level = assistant.thinking_level
    else:
        thinking_level = thinking_override

    # Use default_model from shell_state if set
    model_name = shell_state.get("default_model", assistant.model_name)

    from hobees.core.telemetry import build_telemetry_handler
    _telemetry = build_telemetry_handler(
        bee_provider, bee_name=assistant.name, model_name=model_name, thread_id=thread_id
    )
    model = get_chat_model(
        bee_provider,
        model_name,
        assistant.temperature,
        callbacks=[_telemetry],
        thinking_level=thinking_level,
    )
    tools = get_tools(assistant.tool_names)

    memory_namespaces = extract_namespaces(global_=True, bee_name=assistant.name)
    memory_block = build_memory_block(memory_namespaces)

    # Load assistant skills within a session to avoid detached instance issues
    with session_scope() as session:
        assistant = session.query(Bee).filter_by(name=assistant.name).first()
        assistant_skill_names = [skill.name for skill in assistant.skills] if assistant else []
    
    bee_skills = [
        {"name": s["name"], "description": s["description"]}
        for s in get_skill_metadata()
        if s["name"] in assistant_skill_names
    ]

    # Enhanced system prompt with hobees knowledge
    hobees_knowledge = """
## Hobees System Knowledge
You are the hobees assistant. You know the hobees system inside out:

**Core Commands:**
- `/provider add|list|models|test|remove` - Manage LLM providers (OpenAI, Anthropic, Ollama, vLLM, etc.)
- `/bee create|list|update|delete|thinking` - Create worker bees with specific roles, models, tools
- `/hive create|add-bee|remove-bee|list|use|auto|thinking` - Create teams of bees under a supervisor
- `/chat bee|hive <name>` - Direct chat with a specific bee or hive
- `/goal <goal>` - Queen auto-mode: dynamically creates hive for goal
- `/memory add|list|forget|show` - Cross-session memory (global, hive:, bee: namespaces)
- `/skill create|list|show|save-last|assign|unassign|sync` - Progressive skill library
- `/session save|load|list|delete` - Named session persistence
- `/thinking off|low|medium|high|auto` - Session thinking level override
- `/compact` - Compress conversation history

**Key Concepts:**
- **Providers**: LLM endpoints (api_key_env stored, never plaintext keys)
- **Bees**: Reusable agents with role, system_prompt, provider, model, tools, thinking_level
- **Hives**: Teams of bees under a Supervisor (many-to-many memberships)
- **Queen**: Meta-orchestrator that inspects roster and creates dynamic hives
- **Project Root**: Working directory captured at startup; hives can have subproject paths
- **File Tools**: read_file, write_file, list_directory resolve relative to project root
- **Thinking Levels**: off/low/medium/high mapped per provider (OpenAI reasoning_effort, Anthropic thinking, etc.)
- **Auto Model Discovery**: /provider models fetches from local (Ollama, vLLM, llama.cpp) or remote

**When users ask about hobees:**
- Explain concepts clearly with examples
- Suggest relevant commands
- Offer to help set up providers, bees, or hives
- Reference the current project context when relevant
"""

    system_prompt_parts = []
    if assistant.system_prompt:
        system_prompt_parts.append(assistant.system_prompt)
    system_prompt_parts.append(hobees_knowledge)
    if memory_block:
        system_prompt_parts.append(memory_block)
    if bee_skills:
        skills_text = "\n".join(f"- {s['name']}: {s['description']}" for s in bee_skills)
        system_prompt_parts.append(f"## Available Skills (use load_skill to read)\n{skills_text}")

    full_system_prompt = "\n\n".join(system_prompt_parts) if system_prompt_parts else None

    saver, checkpoint_connection = _get_checkpointer(db_url)

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=full_system_prompt,
        name=assistant.name,
        checkpointer=saver,
    )

    # Streaming with thoughts panel
    thoughts_buffer = []  # Last 4 thought lines
    full_response = ""
    
    def format_thought(msg):
        """Extract thought/action from message."""
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get('name', 'unknown')
                args = tc.get('args', {})
                # Truncate args for display
                args_str = str(args)[:80] + ('...' if len(str(args)) > 80 else '')
                return f"🔧 {name}({args_str})"
        if hasattr(msg, 'content') and msg.content:
            # Check if it's a tool result or thinking
            content = str(msg.content)
            if content.startswith('{') or 'tool_result' in content.lower():
                return f"📤 Result: {content[:100]}..." if len(content) > 100 else f"📤 {content}"
            if len(content) > 120:
                return f"💭 {content[:120]}..."
            return f"💭 {content}"
        return ""
    
    def make_layout():
        """Create the live layout with thoughts panel and output."""
        # Thoughts panel (last 4)
        thoughts_text = Text()
        for t in thoughts_buffer[-4:]:
            thoughts_text.append(t + "\n", style="dim cyan")
        if not thoughts_buffer:
            thoughts_text.append("Waiting for agent...\n", style="dim")
        thoughts_panel = Panel(thoughts_text, title="🧠 Thoughts & Actions", border_style="cyan", height=6)
        
        # Output panel
        output_text = Text(full_response, style="white")
        output_panel = Panel(output_text, title="💬 Response", border_style="green")
        
        return Group(thoughts_panel, output_panel)
    
    console.print()  # Add spacing
    console.print(f"[bold cyan]💭 {assistant.name} is thinking...[/bold cyan]")
    
    full_response = ""
    cancel_flag = {"cancelled": False}
    
    try:
        # Token-level streaming: thinking and answer are printed as generated.
        # Start escape key listener
        listener_task = asyncio.create_task(_stdin_escape_listener(cancel_flag))
        stream_aiter = None
        try:
            streamer = DeltaStreamer()
            stream_open = False
            stream_aiter = agent.astream(
                {"messages": [("user", user_input)]},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="messages",
            )
            async for item in stream_aiter:
                if cancel_flag.get("cancelled") or shell_state.get("cancel_task"):
                    console.print("\n[dim]Cancelled.[/dim]")
                    break
                for _kind, _text in streamer.feed(item):
                    if _kind == "thinking":
                        if not stream_open:
                            console.print("[dim cyan]\U0001F4AD thinking...[/dim cyan]")
                            stream_open = True
                        console.print(_text, style="dim cyan", end="", markup=False)
                    elif _kind == "action":
                        if stream_open:
                            console.print()
                            stream_open = False
                        console.print(_text, style="dim cyan", markup=False)
                    else:
                        if stream_open:
                            console.print()
                            console.print()
                            stream_open = False
                        console.print(_text, end="", highlight=False, markup=False)
        finally:
            # Properly close the async generator to avoid pending task warnings
            if stream_aiter is not None:
                try:
                    await stream_aiter.aclose()
                except Exception:
                    pass
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        
        if stream_open:
            console.print()
        full_response = streamer.text
        console.print()  # New line after streaming
        console.print()
        
        # Telemetry
        from hobees.db.analytics import run_thread_usage
        usage = run_thread_usage(thread_id)
        if usage:
            events = usage.get('events', 0) or 0
            in_toks = usage.get('input_tokens', 0) or 0
            out_toks = usage.get('output_tokens', 0) or 0
            cost = usage.get('estimated_cost_usd', 0) or 0.0
            console.print(f"  tokens: {in_toks:,} in / {out_toks:,} out • ${cost:.4f} • {events} calls")
    except Exception as exc:
            console.print(f"\n{ERROR} Error: {exc}")
    finally:
        if checkpoint_connection:
            checkpoint_connection.close()


__all__ = ["_shell_loop"]