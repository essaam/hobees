"""Full-screen TUI for hobees interactive shell with streaming support."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from prompt_toolkit import Application
from prompt_toolkit.completion import merge_completers
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window, HSplit, VSplit, Float, FloatContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.output import Output
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.styles import Style
from prompt_toolkit.patch_stdout import patch_stdout

from hobees.cli.icons import (
    APP, BEE, HIVE, QUEEN, PROVIDER, TOOL, ACTIVE,
    SUCCESS, WARN, ERROR, MEMORY, SKILL, COMPACT, THINKING
)
from hobees.db.models import LLMProvider, Bee, Hive
from hobees.db.session import session_scope
from hobees.config import settings
from hobees.core.streaming import DeltaStreamer
from hobees.core.tracing import EventBroker, HiveTraceEvent
from hobees.cli.commands import TUI_COMMANDS
from hobees.cli.completion import (
    FilePathCompleter,
    SlashCommandCompleter,
    add_completion_accept_binding,
)

logger = logging.getLogger(__name__)


class _OutputLexer(Lexer):
    """Apply per-message styles to selectable output text."""

    def __init__(self) -> None:
        self.line_styles: list[str] = []

    def lex_document(self, document):
        def get_line(line_number: int):
            style = (
                self.line_styles[line_number]
                if line_number < len(self.line_styles)
                else "class:output"
            )
            return [(style, document.lines[line_number])]

        return get_line


@dataclass
class TUIState:
    """State for the TUI application."""
    active_hive: Optional[str] = None
    thinking_override: str = "auto"  # auto | off | low | medium | high
    thread_id: Optional[str] = None
    provider: Optional[LLMProvider] = None
    db_url: Optional[str] = None
    running: bool = True
    chat_mode: bool = False
    chat_target: Optional[str] = None  # "bee:name" or "hive:name"
    chat_agent: Any = None
    chat_checkpointer: Any = None
    chat_hive_data: Any = None
    default_model: Optional[str] = None
    # While set, the input line answers this prompt instead of running a command.
    pending_prompt: Any = None
    prompt_label: str = ""
    # Task cancellation flag
    cancel_task: bool = False
    # Live Comms pane state
    show_comms: bool = False
    comms_buffer: list[dict] = field(default_factory=list)


class _FollowWindow(Window):
    """Track whether scrolling should continue following new output."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.follow_output = True

    def _scroll_up(self) -> None:
        super()._scroll_up()
        self.follow_output = False

    def _scroll_down(self) -> None:
        super()._scroll_down()
        info = self.render_info
        if info is not None:
            self.follow_output = (
                self.vertical_scroll + info.window_height >= info.content_height
            )

    def scroll_by(self, lines: int) -> None:
        """Scroll by ``lines`` (negative scrolls towards the newest output)."""
        info = self.render_info
        if lines > 0:
            self.follow_output = False
            self.vertical_scroll = max(0, self.vertical_scroll - lines)
        else:
            self.vertical_scroll = max(0, self.vertical_scroll - lines)
            if info is not None:
                self.follow_output = (
                    self.vertical_scroll + info.window_height >= info.content_height
                )


class HobeesTUI:
    """Full-screen TUI for hobees."""
    
    def __init__(self):
        self.state = TUIState()
        self.output_buffer = []
        self._output_lexer = _OutputLexer()
        self._setup_ui()
        self._setup_bindings()
        
    def _setup_ui(self):
        """Setup the UI layout."""
        # Output area (scrollable, auto-follows the newest line, selectable)
        self.output_area = TextArea(
            text="",
            multiline=True,
            read_only=True,
            style="class:output",
            lexer=self._output_lexer,
            scrollbar=True,
        )
        self.output_window = _FollowWindow(
            content=self.output_area.control,
            wrap_lines=True,
            always_hide_cursor=False,
        )
        
        # Comms/Live Activity pane (for hive chat, selectable)
        self.comms_area = TextArea(
            text="",
            multiline=True,
            read_only=True,
            style="class:comms",
            scrollbar=True,
        )
        self.comms_window = _FollowWindow(
            content=self.comms_area.control,
            wrap_lines=True,
            always_hide_cursor=False,
        )
        
        # Input area (fixed at bottom)
        self.input_area = TextArea(
            multiline=False,
            prompt=self._get_prompt,
            accept_handler=self._on_accept,
            style="class:input-area",
            completer=merge_completers(
                [
                    SlashCommandCompleter(
                        TUI_COMMANDS, enabled=lambda: not self.state.chat_mode
                    ),
                    FilePathCompleter(
                        enabled=lambda: self.state.pending_prompt is None
                    ),
                ]
            ),
            complete_while_typing=True,
        )
        
        # Status bar (bottom right)
        self.status_control = FormattedTextControl(
            lambda: self._get_status_text(),
            focusable=False,
        )
        self.status_window = Window(
            content=self.status_control,
            height=1,
            style="class:status-bar",
            align=2,  # right align
        )
        
        # Main layout: title + (output | comms) + status + input
        # We use a function to dynamically choose layout based on show_comms
        self._build_layout()
        
        # Style
        self.style = Style.from_dict({
            "title": "bold fg:#FFD700",
            "output": "fg:#FFFFFF",
            "output.user": "bold fg:#00FF00",
            "output.assistant": "fg:#00FFFF",
            "output.system": "fg:#FFA500",
            "output.error": "bold fg:#FF0000",
            "output.warn": "fg:#FFA500",
            "output.success": "bold fg:#00FF00",
            "output.info": "fg:#888888",
            "output.thinking": "fg:#9a9a9a",
            "output.action": "fg:#ccbbff",
            "output.telemetry": "fg:#888888",
            "comms": "fg:#FFFFFF",
            "comms.timestamp": "fg:#888888",
            "comms.delegate": "bold fg:#FFD700",
            "comms.tool": "fg:#00FFFF",
            "comms.bee_reply": "fg:#00FF00",
            "comms.synthesis": "fg:#FFA500",
            "comms.thought": "fg:#9a9a9a",
            "comms.hive_start": "bold fg:#00FF00",
            "comms.hive_complete": "bold fg:#00FF00",
            "comms.hive_error": "bold fg:#FF0000",
            "input-area": "bg:#222222 fg:#FFFFFF",
            "status-bar": "bg:#333333 fg:#FFFFFF",
            "prompt": "bold fg:#FFD700",
        })
        
    def _get_title(self):
        """Get the title bar text."""
        return [
            ("class:title", f" {APP} hobees "),
            ("class:title", "│ "),
            ("class:title", "Interactive Multi-Agent Orchestrator "),
        ]
    
    def _build_layout(self):
        """Build the main layout, switching between single and split pane."""
        if self.state.show_comms:
            # Split pane: output on left, comms on right
            main_pane = VSplit([
                self.output_window,
                Window(width=1, style="class:divider"),  # Vertical separator
                self.comms_window,
            ])
        else:
            # Single pane: just output
            main_pane = self.output_window
        
        root = HSplit([
            Window(height=1, style="class:title", content=FormattedTextControl(self._get_title)),
            main_pane,
            self.status_window,
            self.input_area,
        ])
        self.layout = Layout(
            FloatContainer(
                content=root,
                floats=[
                    Float(
                        xcursor=True,
                        ycursor=True,
                        content=CompletionsMenu(max_height=4, scroll_offset=1),
                    )
                ],
            )
        )
    
    def _update_output_buffer(self):
        """Update the output TextArea buffer with formatted text."""
        styles = {
            "user": "class:output.user",
            "assistant": "class:output.assistant",
            "system": "class:output.system",
            "error": "class:output.error",
            "warn": "class:output.warn",
            "success": "class:output.success",
            "info": "class:output.info",
            "thinking": "class:output.thinking",
            "action": "class:output.action",
            "telemetry": "class:output.telemetry",
        }
        lines = []
        line_styles = []
        for item in self.output_buffer:
            item_type = item["type"]
            text = item["text"]
            if item_type == "user":
                text = f"> {text}"
            elif item_type in ("thinking", "action"):
                text = f"  {text}"
            item_lines = text.splitlines() or [""]
            lines.extend(item_lines)
            line_styles.extend([styles.get(item_type, "class:output")] * len(item_lines))
        self._output_lexer.line_styles = line_styles
        text = "\n".join(lines) + "\n" if lines else ""
        # Temporarily disable read-only to update buffer
        original_ro = self.output_area.buffer.read_only
        from prompt_toolkit.filters import Condition
        self.output_area.buffer.read_only = Condition(lambda: False)
        try:
            self.output_area.buffer.text = text
            # Auto-scroll to bottom
            self.output_area.buffer.cursor_position = len(text)
        finally:
            self.output_area.buffer.read_only = original_ro
    
    def _update_comms_buffer(self):
        """Update the comms TextArea buffer with formatted text."""
        if not self.state.comms_buffer:
            text = "  [Live Comms] Waiting for hive activity...\n"
        else:
            lines = []
            for item in self.state.comms_buffer:
                etype = item.get("event_type", "")
                timestamp = item.get("timestamp", "")
                time_str = ""
                if timestamp:
                    try:
                        time_str = timestamp.split("T")[-1][:12]
                    except Exception:
                        time_str = timestamp[:12]
                
                source = item.get("source", "")
                target = item.get("target", "")
                payload = item.get("payload", {})
                
                if etype == "HIVE_START":
                    lines.append(f"  [{time_str}] 🟢 HIVE STARTED")
                    if payload.get("project_root"):
                        lines.append(f"       Project: {payload['project_root']}")
                elif etype == "HIVE_COMPLETE":
                    lines.append(f"  [{time_str}] ✅ HIVE COMPLETE")
                elif etype == "HIVE_ERROR":
                    lines.append(f"  [{time_str}] ❌ HIVE ERROR")
                elif etype == "DELEGATE":
                    subtask = payload.get("subtask_preview", "")
                    lines.append(f"  [{time_str}] 📤 DELEGATE → {target}")
                    if subtask:
                        lines.append(f"       Task: {str(subtask)[:80]}")
                elif etype == "WORKER_START":
                    lines.append(f"  [{time_str}] 🐝 WORKER STARTED: {target}")
                elif etype == "WORKER_END":
                    status = payload.get("status", "completed")
                    lines.append(f"  [{time_str}] ✓ WORKER {status.upper()}: {source}")
                elif etype == "TOOL_START":
                    tool_name = payload.get("tool_name", "")
                    lines.append(f"  [{time_str}] 🔧 TOOL: {tool_name}")
                elif etype == "TOOL_END":
                    duration = payload.get("duration_ms", 0)
                    status = "failed" if payload.get("failed") else "done"
                    lines.append(f"  [{time_str}] ✓ TOOL {status} ({duration}ms)")
                elif etype == "BEE_REPLY":
                    content = payload.get("content_preview", "")
                    lines.append(f"  [{time_str}] 🐝 {source} → {target}")
                    if content:
                        lines.append(f"       {str(content)[:80]}")
                elif etype == "SUPERVISOR_SYNTHESIS":
                    content = payload.get("content_preview", "")
                    lines.append(f"  [{time_str}] 🧠 SUPERVISOR SYNTHESIS")
                    if content:
                        lines.append(f"       {str(content)[:80]}")
                else:
                    lines.append(f"  [{time_str}] {etype} | {source} -> {target}")
            text = "\n".join(lines) + "\n"
        # Temporarily disable read-only to update buffer
        original_ro = self.comms_area.buffer.read_only
        from prompt_toolkit.filters import Condition
        self.comms_area.buffer.read_only = Condition(lambda: False)
        try:
            self.comms_area.buffer.text = text
            # Auto-scroll to bottom
            self.comms_area.buffer.cursor_position = len(text)
        finally:
            self.comms_area.buffer.read_only = original_ro
    
    def _get_prompt(self):
        """Get the input prompt."""
        if self.state.pending_prompt is not None:
            return [("class:prompt", self.state.prompt_label)]
        if self.state.chat_mode:
            target = self.state.chat_target or ""
            return [
                ("class:prompt", f"{target} > "),
            ]
        else:
            active = self.state.active_hive or "hobees"
            thinking = self.state.thinking_override or "auto"
            thinking_str = f" {THINKING} {thinking}" if thinking != "auto" else ""
            return [
                ("class:prompt", f"{APP} ({active}){thinking_str} > "),
            ]
            
    def _get_status_text(self):
        """Get status bar text (bottom right)."""
        if self.state.provider:
            provider_name = self.state.provider.alias
            # Use selected default_model if set, otherwise provider's default_model
            model_name = self.state.default_model or self.state.provider.default_model or "none"
        else:
            provider_name = "none"
            model_name = "none"
        return [
            ("class:status-bar", f" {PROVIDER} {provider_name} "),
            ("class:status-bar", f"│ "),
            ("class:status-bar", f"{PROVIDER} {model_name} "),
            ("class:status-bar", " "),
        ]
        
    def _setup_bindings(self):
        """Setup key bindings."""
        kb = KeyBindings()
        add_completion_accept_binding(kb)
        
        @kb.add("c-c")
        def _(event):
            """Exit on Ctrl+C."""
            self.state.running = False
            event.app.exit()

        @kb.add("c-d")
        def _(event):
            """Exit on Ctrl+D."""
            self.state.running = False
            event.app.exit()
            
        @kb.add("escape")
        def _(event):
            """Cancel ongoing task on Esc."""
            if self.state.cancel_task:
                # Already cancelling, force exit
                self.state.running = False
                event.app.exit()
            else:
                self.state.cancel_task = True
                self._add_output("warn", "Cancelling... (press Esc again to force exit)")
                event.app.invalidate()
            
        @kb.add("c-l")
        def _(event):
            """Clear output on Ctrl+L."""
            self.output_buffer.clear()
            event.app.invalidate()
            
        # Scroll the output pane back/forward (mouse wheel also works; these
        # keys make scroll-back reachable without a mouse).
        @kb.add("pageup")
        def _(event):
            self._scroll_output(up=True)

        @kb.add("pagedown")
        def _(event):
            self._scroll_output(up=False)

        # Allow typing / - insert the character
        @kb.add("/")
        def _(event):
            """Insert / character."""
            event.app.current_buffer.insert_text("/")
                
        self.kb = kb

    def _scroll_output(self, up: bool) -> None:
        """Scroll the output pane by one page."""
        info = self.output_window.render_info
        page = max(1, (info.window_height if info else 10) - 1)
        self.output_window.scroll_by(page if up else -page)
        app = getattr(self, "app", None)
        if app is not None:
            app.invalidate()

    def _on_accept(self, buffer):
        """Handle input acceptance."""
        text = buffer.text
        if not text.strip():
            return

        pending = self.state.pending_prompt
        if pending is not None:
            if not pending.done():
                pending.set_result(text.strip())
            self.state.pending_prompt = None
            self.state.prompt_label = ""
            app = getattr(self, "app", None)
            if app is not None:
                app.invalidate()
            return

        task = asyncio.create_task(self._process_input(text.strip()))
        task.add_done_callback(self._report_background_error)

    def _report_background_error(self, task: "asyncio.Task") -> None:
        """Surface exceptions raised by a background input task.

        Without this, a failing handler (e.g. a forgotten ``await``, which
        silently returns a never-run coroutine) leaves the UI looking like
        nothing happened at all.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        # Shared CLI handlers signal bad input with typer.Exit; inside the TUI
        # that only cancels the command, so do not present it as a crash.
        import typer

        if isinstance(exc, (typer.Exit, SystemExit)):
            self._add_output("warn", "Command cancelled.")
            return
        self._add_output("error", f"{type(exc).__name__}: {exc}")
        
    async def _process_input(self, text: str):
        """Process user input."""
        if not text.strip():
            return
            
        # If in chat mode, handle as chat input
        if self.state.chat_mode:
            await self._handle_chat_input(text)
        # If text starts with /, handle as slash command
        elif text.startswith("/"):
            parts = text.split()
            if not parts:
                return
            cmd = parts[0].lstrip("/")
            args = parts[1:] if len(parts) > 1 else []
            await self._handle_command(cmd, args)
        elif self.state.active_hive:
            hive_name = self.state.active_hive
            await self._start_hive_chat(hive_name)
            if self.state.chat_hive_data:
                await self._handle_chat_input(text)
        # Otherwise, treat as chat with assistant (if provider available)
        elif self.state.provider:
            await self._chat_with_assistant(text)
        else:
            self._add_output("error", "No provider selected. Use /provider add or /provider list to select one.")
            
    async def _handle_command(self, cmd: str, args: list[str]):
        """Handle slash commands."""
        if cmd in ("quit", "exit"):
            if self.state.chat_mode:
                await self._exit_chat()
            self.state.running = False
            self.app.exit()
            return
            
        if cmd in ("help", ""):
            # "" happens for a bare "/", which is how users ask for the list.
            self._add_output("info", "Available commands (/ then Tab or keep typing):")
            for name, (desc, subcmds) in sorted(TUI_COMMANDS.items()):
                sub = f" ({', '.join(subcmds)})" if subcmds else ""
                self._add_output("info", f"  /{name:<12} {desc}{sub}")
            return
            
        if cmd == "clear":
            self.output_buffer.clear()
            self.app.invalidate()
            return
            
        if cmd == "thinking":
            if not args:
                self._add_output("info", f"Current thinking: {self.state.thinking_override}")
                return
            level = args[0]
            if level in ("off", "low", "medium", "high", "auto"):
                self.state.thinking_override = level
                self._add_output("info", f"Thinking level set to: {level}")
            else:
                self._add_output("error", f"Invalid level: {level}")
            return
        
        if cmd == "cancel":
            self.state.cancel_task = True
            self._add_output("warn", "Cancellation requested. The current task will stop at the next checkpoint.")
            return
            
        if cmd == "chat":
            if not args:
                self._add_output("info", "Usage: /chat bee <name> | /chat hive <name> | /chat list")
                return
                
            subcmd = args[0]
            if subcmd == "list":
                await self._list_chat_targets()
                return
                
            if subcmd == "bee" and len(args) > 1:
                await self._start_bee_chat(args[1])
                return
                
            if subcmd == "hive" and len(args) > 1:
                await self._start_hive_chat(args[1])
                return
                
            self._add_output("error", "Usage: /chat bee <name> | /chat hive <name> | /chat list")
            return

        if cmd == "hive":
            if not args:
                self._add_output("info", "Hive commands: list, remove [numbers], use <name>, auto, artifacts [name], trace [name]")
                return
            subcmd = args[0]
            if subcmd == "list":
                await self._list_hives()
            elif subcmd == "remove":
                await self._remove_hives(args[1:])
            elif subcmd == "use" and len(args) > 1:
                await self._start_hive_chat(args[1])
            elif subcmd == "auto":
                self.state.active_hive = None
                self._add_output("success", "Switched to Queen auto-mode")
            elif subcmd == "artifacts":
                target = args[1] if len(args) > 1 else (self.state.active_hive or (self.state.chat_target.replace(f"{HIVE} ", "") if self.state.chat_target and HIVE in self.state.chat_target else None))
                await self._show_hive_artifacts(target)
            elif subcmd == "trace":
                target = args[1] if len(args) > 1 else (self.state.active_hive or (self.state.chat_target.replace(f"{HIVE} ", "") if self.state.chat_target and HIVE in self.state.chat_target else None))
                await self._show_hive_trace(target)
            else:
                self._add_output("info", "Hive commands: list, remove [numbers], use <name>, auto, artifacts [name], trace [name]")
            return
            
        if cmd == "provider":
            if not args:
                self._add_output(
                    "info",
                    "Provider commands: add, list, models <alias> (inspect), use [alias|number] (switch)",
                )
                return
            subcmd = args[0]
            if subcmd == "list":
                await self._list_providers()
            elif subcmd == "add":
                await self._add_provider_interactive()
            elif subcmd == "models":
                if len(args) > 1:
                    await self._show_provider_models(args[1])
                else:
                    await self._show_provider_models(
                        self.state.provider.alias if self.state.provider else ""
                    )
            elif subcmd == "use":
                await self._switch_provider(args[1] if len(args) > 1 else None)
            elif subcmd == "edit":
                await self._edit_provider(args[1] if len(args) > 1 else None)
            else:
                self._add_output(
                    "info",
                    "Provider commands: add, list, models <alias> (inspect), use [alias|number] (switch), edit [alias|number]",
                )
            return

        if cmd == "assistant":
            if not args or args[0] == "show":
                await self._show_assistant()
            elif args[0] == "use":
                await self._switch_provider(args[1] if len(args) > 1 else None)
                if len(args) > 2:
                    await self._change_provider_model(args[2])
            elif args[0] == "model":
                await self._change_provider_model(args[1] if len(args) > 1 else None)
            else:
                self._add_output("info", "Assistant commands: show, use <provider> [model], model [name]")
            return
            
        # Add more commands as needed
        self._add_output("error", f"Unknown command: /{cmd}. Type /help for help.")
        
    async def _list_providers(self):
        """List all providers, marking the assistant's current one."""
        from hobees.cli.shell import get_assistant_selection

        with session_scope() as session:
            providers = session.query(LLMProvider).order_by(LLMProvider.id).all()
        if providers:
            current_provider, current_model = get_assistant_selection()
            self._add_output("info", "Available Providers:")
            for idx, p in enumerate(providers, 1):
                active = " ◀ assistant" if current_provider and p.id == current_provider.id else ""
                self._add_output(
                    "info",
                    f"  ({idx}) {p.alias} ({p.provider_type}) - default: {p.default_model or 'none'}{active}",
                )
            if current_provider:
                self._add_output(
                    "info",
                    f"Assistant uses {current_provider.alias} / {current_model or 'no model'}",
                )
        else:
            self._add_output("info", "No providers registered.")

    async def _show_provider_models(self, alias: str):
        """List the models discovered for a provider (read-only)."""
        from hobees.core.model_discovery import fetch_provider_models
        from hobees.db.models import LLMProvider

        if not alias:
            self._add_output("error", "Usage: /provider models <alias>")
            return

        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=alias).first()
        if not provider:
            self._add_output("error", f"Provider {alias!r} not found")
            return
        
        import os
        # Check if API key is set (for providers that require it)
        if provider.api_key_env != "NONE" and not os.environ.get(provider.api_key_env):
            self._add_output("warn", f"API key env var '{provider.api_key_env}' is not set.")
            if await self._confirm(f"Set api_key_env to NONE and try anyway?"):
                provider.api_key_env = "NONE"
            else:
                return

        try:
            models = fetch_provider_models(provider, refresh_cache=False)
        except Exception as e:
            self._add_output("error", f"Failed to fetch models: {e}")
            return

        if models:
            self._add_output("info", f"Models for {alias}:")
            for m in models:
                self._add_output("info", f"  {m}")
        else:
            self._add_output("warn", f"No models found for {alias} (or provider not yet configured).")
        
    async def _add_provider_interactive(self):
        """Interactive provider creation in TUI."""
        from hobees.cli.provider_cmd import VALID_TYPES
        from hobees.core.model_discovery import fetch_provider_models
        from hobees.db.models import LLMProvider
        from hobees.db.session import session_scope
        
        self._add_output("info", "Create New Provider")
        
        # Get provider alias
        alias = await self._prompt_input("Provider alias: ")
        if not alias:
            return
            
        # Get provider type
        self._add_output("info", f"Provider types: {', '.join(VALID_TYPES)}")
        provider_type = await self._prompt_input("Provider type: ")
        if provider_type not in VALID_TYPES:
            self._add_output("error", f"Invalid provider type. Must be one of: {VALID_TYPES}")
            return
            
        base_url = None
        if provider_type == "openai_compatible":
            base_url = await self._prompt_input("Base URL (e.g. http://localhost:8080/v1): ")
            
        api_key_env = await self._prompt_input("API key env var (or NONE): ")
        if not api_key_env:
            api_key_env = "NONE"
            
        # Fetch models if openai_compatible
        models = []
        if provider_type == "openai_compatible" and base_url:
            self._add_output("info", f"Fetching available models from {base_url}...")
            temp_provider = LLMProvider(
                alias=alias,
                provider_type=provider_type,
                base_url=base_url,
                api_key_env=api_key_env,
            )
            models = fetch_provider_models(temp_provider, refresh_cache=True)
            if models:
                self._add_output("info", f"Discovered {len(models)} models.")
            else:
                self._add_output("warn", "No models discovered. Check base_url and API key.")
        
        # Select model
        default_model = None
        if models:
            self._add_output("info", "Available models:")
            for idx, model in enumerate(sorted(models), 1):
                self._add_output("info", f"  ({idx}) {model}")
            self._add_output("info", "  (custom) Enter custom model name")
            
            ordered = sorted(models)
            choice = await self._prompt_input("Select model (number or 'custom'): ")
            if choice.lower() == "custom":
                default_model = await self._prompt_input("Enter model name: ")
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(ordered):
                        default_model = ordered[idx]
                except ValueError:
                    default_model = await self._prompt_input("Enter model name: ")
        else:
            default_model = await self._prompt_input("Default model (optional): ")
            
        if not default_model:
            default_model = None
            
        input_cost = await self._prompt_input("Input cost per 1M tokens (USD): ", "0")
        output_cost = await self._prompt_input("Output cost per 1M tokens (USD): ", "0")
        
        # Create the provider
        try:
            input_cost_f = float(input_cost)
            output_cost_f = float(output_cost)
        except ValueError:
            self._add_output("error", "Invalid cost values")
            return
            
        from hobees.cli.provider_cmd import cmd_provider_add
        cmd_provider_add(
            alias, provider_type, base_url, api_key_env, default_model,
            input_cost_f, output_cost_f, interactive=False
        )
        
        # Update provider with models
        if models:
            with session_scope() as session:
                provider = session.query(LLMProvider).filter_by(alias=alias).first()
                if provider:
                    provider.available_models = models
                    from datetime import datetime, timezone
                    provider.models_refreshed_at = datetime.now(timezone.utc)
        
        # Update TUI state if no provider was selected
        if self.state.provider is None:
            with session_scope() as session:
                new_provider = session.query(LLMProvider).filter_by(alias=alias).first()
                if new_provider:
                    self.state.provider = new_provider
                    self._add_output("info", f"Now using provider: {new_provider.alias}")
        
    async def _prompt_input(self, prompt: str, default: str = "") -> str:
        """Ask for a line of input without leaving the TUI.

        A blocking ``input()`` would fight prompt_toolkit for the terminal, so
        the question is shown on the input prompt and ``_on_accept`` resolves
        the future when the user presses Enter.
        """
        if self.state.pending_prompt is not None:
            # A prompt is already open; do not stack a second one.
            return default

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.state.pending_prompt = future
        self.state.prompt_label = prompt if prompt.rstrip().endswith((":", ">")) else f"{prompt}: "
        self._add_output("info", f"{self.state.prompt_label}{default}" if default else self.state.prompt_label.rstrip())
        app = getattr(self, "app", None)
        if app is not None:
            app.invalidate()

        try:
            answer = await future
        finally:
            self.state.pending_prompt = None
            self.state.prompt_label = ""
        return answer or default

    async def _choose(
        self, title: str, options: list[str], default: str | None = None
    ) -> str | None:
        """Numbered picker that works inside the full-screen app."""
        if not options:
            return default

        self._add_output("info", title)
        for idx, option in enumerate(options, 1):
            marker = " (current)" if default and option == default else ""
            self._add_output("info", f"  ({idx}) {option}{marker}")
        self._add_output("info", f"  (c) type a custom value" + (f" / Enter keeps {default}" if default else ""))

        answer = (await self._prompt_input("Selection", default or "")).strip()
        if not answer:
            return default
        if answer.lower() in ("c", "custom"):
            return (await self._prompt_input("Value", default or "")).strip() or default
        if answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(options):
                return options[idx]
        for option in options:
            if option.lower() == answer.lower():
                return option
        self._add_output("warn", f"{answer!r} is not in the list; keeping {default or 'unchanged'}.")
        return default

    async def _confirm(self, prompt: str) -> bool:
        """Yes/no confirmation in TUI."""
        answer = (await self._prompt_input(f"{prompt} (y/n)", "")).strip().lower()
        return answer in ("y", "yes")

    async def _switch_provider(self, alias_or_num: str | None = None):
        """Switch the assistant's provider, resolving its model the same way
        the shell does, and persist the choice."""
        from hobees.db.session import session_scope
        from hobees.db.models import LLMProvider
        from hobees.core.model_discovery import fetch_provider_models
        from hobees.cli.shell import get_assistant_selection, persist_assistant_selection

        with session_scope() as session:
            providers = session.query(LLMProvider).order_by(LLMProvider.id).all()

        if not providers:
            self._add_output("error", "No providers registered. Use /provider add.")
            return

        if not alias_or_num:
            alias_or_num = await self._choose(
                "Select a provider:",
                [p.alias for p in providers],
                default=(self.state.provider.alias if self.state.provider else None),
            )
            if not alias_or_num:
                return

        provider = None
        if alias_or_num.isdigit():
            idx = int(alias_or_num) - 1
            if 0 <= idx < len(providers):
                provider = providers[idx]
        else:
            provider = next((p for p in providers if p.alias == alias_or_num), None)

        if not provider:
            self._add_output("error", f"Provider {alias_or_num!r} not found")
            return

        current_provider, current_model = get_assistant_selection()
        if current_provider is not None and current_provider.id == provider.id and current_model:
            model_name = current_model
        elif provider.default_model:
            model_name = provider.default_model
        else:
            models = fetch_provider_models(provider, refresh_cache=False)
            if len(models) == 1:
                model_name = models[0]
            elif models:
                model_name = await self._choose(
                    f"Select a model for {provider.alias}:", sorted(models)
                )
            else:
                model_name = await self._prompt_input("Model name", "") or None

        self.state.provider = provider
        self.state.default_model = model_name
        persist_assistant_selection(provider.id, model_name)
        self._invalidate()
        self._add_output(
            "info",
            f"Switched to provider: {provider.alias}"
            + (f" (model: {model_name})" if model_name else ""),
        )

    async def _change_provider_model(self, model_name: str | None = None):
        """Pick the assistant's model for the current provider and persist it."""
        from hobees.core.model_discovery import fetch_provider_models
        from hobees.cli.shell import persist_assistant_selection

        if not self.state.provider:
            self._add_output("error", "No provider selected. Use /provider use <alias> first.")
            return

        if not model_name:
            models = fetch_provider_models(self.state.provider, refresh_cache=False)
            if not models:
                model_name = await self._prompt_input(
                    "Model name", self.state.default_model or self.state.provider.default_model or ""
                )
            else:
                model_name = await self._choose(
                    f"Select a model for {self.state.provider.alias}:",
                    sorted(models),
                    default=self.state.default_model or self.state.provider.default_model,
                )

        if not model_name:
            self._add_output("warn", "Model unchanged.")
            return

        self.state.default_model = model_name
        persist_assistant_selection(self.state.provider.id, model_name)
        self._invalidate()
        self._add_output("info", f"Assistant model set to: {model_name}")

    async def _show_assistant(self):
        """Print the assistant's persisted provider/model."""
        from hobees.cli.shell import get_assistant_selection

        provider, model = get_assistant_selection()
        if not provider:
            self._add_output("warn", "No assistant configured yet.")
            return
        self._add_output(
            "info",
            f"{BEE} assistant — provider: {provider.alias} ({provider.provider_type}), "
            f"model: {model or 'none'}",
        )

    async def _edit_provider(self, alias_or_num: str | None = None):
        """Edit an existing provider's details."""
        from hobees.db.session import session_scope
        from hobees.db.models import LLMProvider
        from hobees.cli.provider_cmd import VALID_TYPES

        with session_scope() as session:
            providers = session.query(LLMProvider).order_by(LLMProvider.id).all()

        if not providers:
            self._add_output("error", "No providers registered.")
            return

        if not alias_or_num:
            alias_or_num = await self._choose(
                "Select a provider to edit:",
                [p.alias for p in providers],
            )
            if not alias_or_num:
                return

        provider = None
        if alias_or_num.isdigit():
            idx = int(alias_or_num) - 1
            if 0 <= idx < len(providers):
                provider = providers[idx]
        else:
            provider = next((p for p in providers if p.alias == alias_or_num), None)

        if not provider:
            self._add_output("error", f"Provider {alias_or_num!r} not found")
            return

        self._add_output("info", f"Editing provider: {provider.alias}")
        self._add_output("info", "Enter new value or press Enter to keep current.")

        # Provider type
        type_choices = VALID_TYPES
        new_type = await self._choose(
            f"Provider type (current: {provider.provider_type}):",
            type_choices,
            default=provider.provider_type,
        )
        if new_type:
            provider.provider_type = new_type

        # Base URL
        new_base_url = await self._prompt_input(
            f"Base URL (current: {provider.base_url or 'none'})",
            "",
        )
        if new_base_url.strip():
            provider.base_url = new_base_url.strip()
        elif new_base_url == "":  # Explicitly cleared
            provider.base_url = None

        # API key env
        new_api_key_env = await self._prompt_input(
            f"API key env var (current: {provider.api_key_env})",
            provider.api_key_env,
        )
        if new_api_key_env:
            provider.api_key_env = new_api_key_env

        # Input cost
        new_input_cost = await self._prompt_input(
            f"Input cost per 1M tokens (current: {provider.input_cost_per_1m})",
            str(provider.input_cost_per_1m),
        )
        try:
            provider.input_cost_per_1m = float(new_input_cost)
        except ValueError:
            self._add_output("warn", "Invalid input cost, keeping current")

        # Output cost
        new_output_cost = await self._prompt_input(
            f"Output cost per 1M tokens (current: {provider.output_cost_per_1m})",
            str(provider.output_cost_per_1m),
        )
        try:
            provider.output_cost_per_1m = float(new_output_cost)
        except ValueError:
            self._add_output("warn", "Invalid output cost, keeping current")

        # Context window
        new_context = await self._prompt_input(
            f"Context window tokens (current: {provider.context_window_tokens})",
            str(provider.context_window_tokens),
        )
        try:
            provider.context_window_tokens = int(new_context)
        except ValueError:
            self._add_output("warn", "Invalid context window, keeping current")

        # If openai_compatible and no base_url, ask
        if provider.provider_type == "openai_compatible" and not provider.base_url:
            new_base_url = await self._prompt_input(
                "Base URL (required for openai_compatible)",
                "",
            )
            if new_base_url:
                provider.base_url = new_base_url.strip()
            else:
                self._add_output("warn", "openai_compatible providers require a base_url")

        self._add_output("info", f"Provider {provider.alias!r} updated")

    async def _show_assistant(self):
        """Print the assistant's persisted provider/model."""
        from hobees.cli.shell import get_assistant_selection

        provider, model = get_assistant_selection()
        if not provider:
            self._add_output("warn", "No assistant configured yet.")
            return
        self._add_output(
            "info",
            f"{BEE} assistant — provider: {provider.alias} ({provider.provider_type}), "
            f"model: {model or 'none'}",
        )

    async def _chat_with_assistant(self, user_input: str):
        """Chat with the default assistant bee."""
        if not self.state.provider:
            self._add_output("error", "No provider selected.")
            return
            
        from hobees.core.llm_factory import get_chat_model
        from hobees.core.tool_registry import get_tools
        from hobees.db.session import session_scope
        from hobees.db.models import Bee
        from hobees.core.memory_manager import extract_namespaces, build_memory_block
        from hobees.core.tool_registry import get_skill_metadata
        from langchain.agents import create_agent
        from hobees.cli.shell import _get_or_create_assistant

        # Get or create assistant bee
        assistant = _get_or_create_assistant(self.state.provider, self.state.db_url)
        if not assistant:
            self._add_output("error", "Could not create assistant bee")
            return

        bee_provider = None
        with session_scope() as session:
            bee_provider = session.query(type(self.state.provider)).filter_by(id=assistant.provider_id).first()

        if not bee_provider:
            self._add_output("error", "Could not find provider for assistant")
            return

        thread_id = self.state.thread_id or uuid.uuid4().hex
        self.state.thread_id = thread_id

        # Set thread context for tool truncation and project root
        from hobees.core.tool_registry import set_thread_context
        project_root = getattr(self.state.provider, 'project_path', None) if self.state.provider else None
        # Use hive's project_path if in a hive, otherwise use provider's default
        if not project_root and self.state.active_hive:
            from hobees.db.session import session_scope
            from hobees.db.models import Hive
            with session_scope() as session:
                hive = session.query(Hive).filter_by(name=self.state.active_hive).first()
                if hive:
                    project_root = hive.project_path
        set_thread_context(thread_id, project_root=project_root)

        thinking_override = self.state.thinking_override
        if thinking_override == "auto":
            thinking_level = assistant.thinking_level
        else:
            thinking_level = thinking_override

        # Use state default_model or assistant's model_name
        model_name = self.state.default_model or assistant.model_name

        from hobees.core.telemetry import build_telemetry_handler
        _telemetry = build_telemetry_handler(
            bee_provider,
            bee_name=assistant.name,
            model_name=model_name,
            thread_id=thread_id,
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

        system_prompt_parts = []
        if assistant.system_prompt:
            system_prompt_parts.append(assistant.system_prompt)
        if memory_block:
            system_prompt_parts.append(memory_block)
        if bee_skills:
            skills_text = "\n".join(f"- {s['name']}: {s['description']}" for s in bee_skills)
            system_prompt_parts.append(f"## Available Skills (use load_skill to read)\n{skills_text}")

        full_system_prompt = "\n\n".join(system_prompt_parts) if system_prompt_parts else None

        from hobees.cli.shell import _get_async_checkpointer
        saver, checkpoint_stack = await _get_async_checkpointer(self.state.db_url)
        try:
            agent = create_agent(
                model=model,
                tools=tools,
                system_prompt=full_system_prompt,
                name=assistant.name,
                checkpointer=saver,
            )

            self._add_output("user", user_input)

            try:
                streamer = DeltaStreamer()
                await self._stream_into_buffer(streamer, agent, user_input, thread_id)
            except Exception as e:
                self._add_output("error", f"Error: {e}")
                return
        finally:
            await checkpoint_stack.aclose()
        
        # Show telemetry footer
        from hobees.db.analytics import run_thread_usage
        usage = run_thread_usage(thread_id)
        if usage:
            events = usage.get('events', 0) or 0
            in_toks = usage.get('input_tokens', 0) or 0
            out_toks = usage.get('output_tokens', 0) or 0
            cost = usage.get('estimated_cost_usd', 0) or 0.0
            self._add_output("telemetry", f"tokens: {in_toks:,} in / {out_toks:,} out • ${cost:.4f} • {events} calls")
        
        
    async def _list_chat_targets(self):
        """List available bees and hives for chat."""
        with session_scope() as session:
            bees = session.query(Bee).all()
            hives = session.query(Hive).all()
            
        if bees:
            self._add_output("info", "Available Bees:")
            for b in bees:
                self._add_output("info", f"  {BEE} {b.name}: {b.role_description} ({b.provider.alias}/{b.model_name})")
        if hives:
            self._add_output("info", "Available Hives:")
            for h in hives:
                members = ", ".join(m.bee.name for m in h.memberships) or "(none)"
                self._add_output("info", f"  {HIVE} {h.name}: {h.supervisor_provider.alias}/{h.supervisor_model_name} - bees: {members}")

    async def _list_hives(self):
        """List all hives in TUI."""
        from hobees.db.models import HiveMembership, LLMProvider
        with session_scope() as session:
            hives = session.query(Hive).order_by(Hive.name).all()
            if not hives:
                self._add_output("warn", "No Hives registered. Use 'hobees hive create' or config import.")
                return
            self._add_output("info", "Registered Working Hives:")
            for h in hives:
                members = ", ".join(m.bee.name for m in h.memberships if m.bee) or "(none)"
                self._add_output("info", f"  {HIVE} {h.name}: {h.supervisor_model_name} (thinking: {h.supervisor_thinking_level or 'medium'}) - workers: {members}")

    async def _remove_hives(self, selections: list[str]) -> None:
        """Interactively remove one or more numbered hives."""
        from hobees.cli.hive_cmd import (
            get_hive_names,
            remove_hives,
            resolve_hive_selection,
        )

        hive_names = get_hive_names()
        if not hive_names:
            self._add_output("warn", "No Hives to remove.")
            return
        self._add_output("info", "Select Hives to remove:")
        for index, name in enumerate(hive_names, 1):
            self._add_output("info", f"  {index}. {name}")

        selection = " ".join(selections)
        if not selection:
            selection = await self._prompt_input(
                "Hive numbers to remove (comma-separated; q to cancel)"
            )
        if selection.lower() in ("q", "quit", "cancel"):
            self._add_output("warn", "Hive removal cancelled.")
            return

        try:
            selected = resolve_hive_selection(selection, hive_names)
        except ValueError as exc:
            self._add_output("error", str(exc))
            return

        confirmation = await self._prompt_input(
            f"Remove {len(selected)} Hive(s): {', '.join(selected)}? Type yes to confirm"
        )
        if confirmation.strip().lower() not in ("y", "yes"):
            self._add_output("warn", "Hive removal cancelled.")
            return

        try:
            removed = remove_hives(selected)
        except ValueError as exc:
            self._add_output("error", str(exc))
            return
        for name in removed:
            self._add_output("success", f"Hive {name!r} removed.")

        if self.state.active_hive in removed:
            self.state.active_hive = None
        chat_hive = self.state.chat_hive_data[0] if self.state.chat_hive_data else None
        if chat_hive and chat_hive.name in removed:
            self.state.chat_hive_data = None
            self.state.chat_mode = False
            self.state.chat_target = None

    async def _show_hive_artifacts(self, name: str | None):
        """Show generated artifacts for a hive."""
        if not name:
            self._add_output("warn", "Specify a hive name: /hive artifacts <name>")
            return
        from hobees.cli.hive_cmd import get_hive_artifacts_dir

        art_dir = get_hive_artifacts_dir(name)
        if not art_dir.exists():
            self._add_output("warn", f"No artifacts directory found for {name} ({art_dir})")
            return
        files = list(art_dir.rglob("*"))
        self._add_output("info", f"Artifacts for {HIVE} {name} ({art_dir.resolve()}):")
        if not files:
            self._add_output("info", "  (No files generated yet)")
        for f in sorted(files):
            if f.is_file():
                rel = f.relative_to(art_dir)
                size = f.stat().st_size
                self._add_output("info", f"  • {rel} ({size:,} bytes)")

    async def _show_hive_trace(self, name: str | None):
        """Show recent trace events for a hive."""
        if not name:
            self._add_output("warn", "Specify a hive name: /hive trace <name>")
            return
        import json
        from hobees.cli.hive_cmd import get_hive_artifacts_dir

        traces_dir = get_hive_artifacts_dir(name) / "traces"
        if not traces_dir.exists():
            self._add_output("warn", f"No traces found for {name}")
            return
        trace_files = sorted(traces_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not trace_files:
            self._add_output("warn", f"No trace files found for {name}")
            return
        latest = trace_files[0]
        self._add_output("info", f"Trace log for {HIVE} {name} ({latest.name}):")
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
                    self._add_output("info", f"  [{t}] {etype} | {src} -> {tgt}: {str(detail)[:70]}")
                except Exception:
                    self._add_output("info", f"  {line.strip()[:80]}")
                
    async def _start_bee_chat(self, name: str):
        """Start chat with a single bee."""
        from hobees.core.llm_factory import get_chat_model
        from hobees.core.tool_registry import get_tools
        from hobees.core.memory_manager import extract_namespaces, build_memory_block
        from hobees.core.tool_registry import get_skill_metadata
        from hobees.db.session import session_scope
        from hobees.db.models import Bee
        from langchain.agents import create_agent
        
        with session_scope() as session:
            bee = session.query(Bee).filter_by(name=name).first()
        if not bee:
            self._add_output("error", f"Bee {name!r} not found")
            return
            
        # Get provider
        bee_provider = None
        with session_scope() as session:
            bee_row = session.query(Bee).filter_by(name=name).first()
            if bee_row:
                from hobees.db.models import LLMProvider
                bee_provider = session.query(LLMProvider).filter_by(id=bee_row.provider_id).first()
                
        if not bee_provider:
            self._add_output("error", f"Could not find provider for bee {name!r}")
            return
            
        thread_id = uuid.uuid4().hex
        self.state.thread_id = thread_id
        
        thinking_override = self.state.thinking_override
        if thinking_override == "auto":
            thinking_level = bee.thinking_level
        else:
            thinking_level = thinking_override
            
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
        
        memory_namespaces = extract_namespaces(global_=True, bee_name=bee.name)
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
        
        from hobees.cli.shell import _get_async_checkpointer
        saver, checkpoint_stack = await _get_async_checkpointer(self.state.db_url)
        try:
            agent = create_agent(
                model=model,
                tools=tools,
                system_prompt=full_system_prompt,
                name=bee.name,
                checkpointer=saver,
            )
        except BaseException:
            await checkpoint_stack.aclose()
            raise
        
        self.state.chat_mode = True
        self.state.chat_target = f"{BEE} {bee.name}"
        self.state.chat_agent = agent
        self.state.chat_checkpointer = (saver, checkpoint_stack)
        
        self._add_output("system", f"Started chat with {BEE} {bee.name} (type 'exit' to return)")
        self.app.invalidate()
        
    async def _start_hive_chat(self, name: str):
        """Start chat with a hive."""
        from hobees.db.session import session_scope
        from hobees.db.models import Hive, Bee, HiveMembership, LLMProvider, Run
        
        with session_scope() as session:
            hive = session.query(Hive).filter_by(name=name).first()
        if not hive:
            self._add_output("error", f"Hive {name!r} not found")
            return
            
        with session_scope() as session:
            memberships = session.query(HiveMembership).filter_by(hive_id=hive.id).all()
            bee_ids = [m.bee_id for m in memberships]
            bees = session.query(Bee).filter(Bee.id.in_(bee_ids)).all() if bee_ids else []
            providers = {p.id: p for p in session.query(LLMProvider).all()}
            
        if not bees:
            self._add_output("warn", f"Hive {name!r} has no bees assigned")
            return
            
        thread_id = uuid.uuid4().hex
        self.state.thread_id = thread_id
        with session_scope() as session:
            run = Run(
                thread_id=thread_id,
                hive_id=hive.id,
                mode="hive",
                goal=f"Interactive chat with Hive {hive.name}",
                status="running",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        
        thinking_override = self.state.thinking_override
        
        self._add_output("system", f"Starting chat with {HIVE} {hive.name}...")
        
        self.state.chat_mode = True
        self.state.chat_target = f"{HIVE} {hive.name}"
        
        self.state.chat_hive_data = (
            hive,
            bees,
            providers,
            thread_id,
            self.state.thinking_override,
            run_id,
            [],
        )
        
        # Enable Live Comms pane
        self.state.show_comms = True
        self.state.comms_buffer.clear()
        self._build_layout()
        
        # Subscribe to EventBroker for live trace events
        self._comms_queue = EventBroker.get_instance().subscribe()
        self._comms_listener_task = asyncio.create_task(self._listen_comms())
        
        self._add_output("system", f"Started chat with {HIVE} {hive.name} (type 'exit' to return)")
        self.app.invalidate()
        
    async def _handle_chat_input(self, text: str):
        """Handle input during chat mode."""
        if text.strip().lower() in ("exit", "quit"):
            await self._exit_chat()
            return
            
        if not text.strip():
            return
            
        self._add_output("user", text)
        if self.state.chat_hive_data and len(self.state.chat_hive_data) >= 7:
            self.state.chat_hive_data[6].append(text)
        
        try:
            if self.state.chat_agent:
                # Bee chat - use streaming
                await self._stream_bee_response(text)
            elif self.state.chat_hive_data:
                # Hive chat - use streaming
                await self._stream_hive_response(text)
        except Exception as e:
            self._add_output("error", f"Error: {e}")
            
    async def _stream_bee_response(self, text: str):
        """Stream response from bee agent."""
        from hobees.db.analytics import run_thread_usage
        
        
        thread_id = self.state.thread_id
        
        try:
            streamer = DeltaStreamer()
            await self._stream_into_buffer(
                streamer, self.state.chat_agent, text, thread_id
            )
        except Exception as e:
            self._add_output("error", f"Error: {e}")
            return
            
        # Show telemetry footer
        usage = run_thread_usage(thread_id)
        if usage:
            events = usage.get('events', 0) or 0
            in_toks = usage.get('input_tokens', 0) or 0
            out_toks = usage.get('output_tokens', 0) or 0
            cost = usage.get('estimated_cost_usd', 0) or 0.0
            self._add_output("telemetry", f"tokens: {in_toks:,} in / {out_toks:,} out • ${cost:.4f} • {events} calls")
            
    async def _stream_hive_response(self, text: str):
        """Stream response from hive agent."""
        from hobees.core.hive_builder import hive_app_async
        from hobees.db.analytics import run_thread_usage
        
        hive, bees, providers, thread_id, thinking_override, run_id, _ = (
            self.state.chat_hive_data
        )

        try:
            async with hive_app_async(
                hive,
                bees,
                providers,
                self.state.db_url,
                thread_id,
                run_id,
                thinking_override,
            ) as app:
                streamer = DeltaStreamer()
                await self._stream_into_buffer(streamer, app, text, thread_id)

        except Exception as e:
            self._add_output("error", f"Error: {e}")
            return
            
        # Show telemetry footer
        usage = run_thread_usage(thread_id)
        if usage:
            events = usage.get('events', 0) or 0
            in_toks = usage.get('input_tokens', 0) or 0
            out_toks = usage.get('output_tokens', 0) or 0
            cost = usage.get('estimated_cost_usd', 0) or 0.0
            self._add_output("telemetry", f"tokens: {in_toks:,} in / {out_toks:,} out • ${cost:.4f} • {events} calls")
            
    async def _exit_chat(self):
        """Exit chat mode."""
        hive_chat_data = self.state.chat_hive_data
        # Clean up comms listener if active
        if hasattr(self, '_comms_listener_task') and self._comms_listener_task:
            self._comms_listener_task.cancel()
            try:
                await self._comms_listener_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, '_comms_queue') and self._comms_queue:
            EventBroker.get_instance().unsubscribe(self._comms_queue)
        
        if self.state.chat_checkpointer:
            _saver, checkpoint_stack = self.state.chat_checkpointer
            await checkpoint_stack.aclose()
                
        self.state.chat_mode = False
        self.state.chat_target = None
        self.state.chat_agent = None
        self.state.chat_checkpointer = None
        if hasattr(self.state, "chat_hive_data"):
            delattr(self.state, "chat_hive_data")

        if hive_chat_data and len(hive_chat_data) >= 7:
            from datetime import datetime, timezone
            from hobees.core.skill_harvester import harvest_completed_run
            from hobees.db.models import Run
            from hobees.db.session import session_scope

            run_id = hive_chat_data[5]
            user_messages = hive_chat_data[6]
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run:
                    if user_messages:
                        run.goal = "\n".join(user_messages)
                    run.status = "completed"
                    run.completed_at = datetime.now(timezone.utc)
            draft = harvest_completed_run(run_id)
            if draft:
                self._add_output(
                    "skill",
                    f"Skill draft {draft['name']!r} generated. "
                    "Review/save it with 'hobees skill save-last' from the CLI.",
                )
        
        # Disable Live Comms pane
        self.state.show_comms = False
        self._build_layout()
            
        self._add_output("system", "Returned to main shell")
        self.app.invalidate()
        
    def _invalidate(self) -> None:
        """Repaint the app when it exists (handlers also run before/after it)."""
        app = getattr(self, "app", None)
        if app is not None:
            app.invalidate()

    def _add_output(self, type_: str, text: str):
        """Add output to buffer."""
        self.output_buffer.append({"type": type_, "text": text})
        if type_ == "user":
            # A new turn: jump back to the newest output.
            self.output_window.follow_output = True
        # Update the TextArea buffers
        self._update_output_buffer()
        self._update_comms_buffer()
        # ``self.app`` does not exist yet while the welcome banner is added, and
        # an error reported during teardown must not raise again.
        app = getattr(self, "app", None)
        if app is not None:
            app.invalidate()

    async def _listen_comms(self):
        """Background task to listen for trace events from EventBroker."""
        try:
            while True:
                event = await self._comms_queue.get()
                # Filter events for current thread if needed
                if event.get("thread_id") == self.state.thread_id:
                    self.state.comms_buffer.append(event)
                    # Limit buffer size
                    if len(self.state.comms_buffer) > 500:
                        self.state.comms_buffer = self.state.comms_buffer[-400:]
                    self._update_comms_buffer()
                    app = getattr(self, "app", None)
                    if app is not None:
                        app.invalidate()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("TUI hive event listener stopped unexpectedly")
            self._add_output("error", f"Live activity listener failed: {exc}")

    async def _stream_into_buffer(self, streamer, agent, user_input: str, thread_id: str) -> str:
        """Stream a graph's token-level output into the output buffer.

        Each kind (``thinking`` / ``assistant``) grows a single buffer entry so
        the UI renders the text as it is generated instead of appending one
        entry per token. ``action`` notices are discrete lines. Returns the
        full answer text.
        """
        self.state.cancel_task = False
        indices: dict[str, int] = {}
        stream_aiter = None
        try:
            stream_aiter = agent.astream(
                {"messages": [("user", user_input)]},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="messages",
            )
            async for item in stream_aiter:
                if self.state.cancel_task:
                    self._add_output("warn", "Task cancelled by user.")
                    break
                for kind, fragment in streamer.feed(item):
                    if kind == "action":
                        self.output_buffer.append({"type": "action", "text": fragment})
                    else:
                        if kind not in indices:
                            self.output_buffer.append({"type": kind, "text": ""})
                            indices[kind] = len(self.output_buffer) - 1
                        self.output_buffer[indices[kind]]["text"] += fragment
                self._update_output_buffer()
        finally:
            # Properly close the async generator to avoid pending task warnings
            if stream_aiter is not None:
                try:
                    await stream_aiter.aclose()
                except Exception:
                    pass
        self.state.cancel_task = False
        return streamer.text
        
    def run(
        self,
        provider: LLMProvider | None,
        db_url: str,
        ctx_obj: dict | None = None,
        model_name: str | None = None,
    ):
        """Run the TUI application."""
        self.state.provider = provider
        self.state.db_url = db_url
        if model_name:
            self.state.default_model = model_name
        
        # Handle session resume
        if ctx_obj:
            if ctx_obj.get("resume_session"):
                from hobees.cli.shell import _load_session
                name = ctx_obj["resume_session"]
                data = _load_session(name)
                if data:
                    self.state.active_hive = data.get("active_hive")
                    self.state.thread_id = data.get("thread_id")
            elif ctx_obj.get("active_hive"):
                self.state.active_hive = ctx_obj["active_hive"]
        
        # Create app
        self.app = self._create_application()

        # Welcome message
        if provider:
            model_display = self.state.default_model or provider.default_model or "none"
            self._add_output("system", f"{APP} hobees Interactive Shell")
            self._add_output("info", f"Provider: {provider.alias} ({provider.provider_type})")
            self._add_output("info", f"Model: {model_display}")
            self._add_output("info", "Type /help for commands, /chat bee <name> to start chatting, or just type to chat with assistant")
        else:
            self._add_output("system", f"{APP} hobees Interactive Shell")
            self._add_output("info", "No provider selected. Use /provider add to add one.")
            self._add_output("info", "Type /help for commands")
        self._add_output(
            "info",
            "Output is selectable with terminal mouse selection; use the terminal's copy shortcut.",
        )
        
        # Focus input area so user can type immediately
        self.app.layout.focus(self.input_area)
        
        # Run
        with patch_stdout():
            self.app.run()

    def _create_application(self, output: Output | None = None) -> Application:
        """Create a TUI app while leaving mouse selection to the terminal."""
        return Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=self.style,
            full_screen=True,
            output=output,
            # Let the terminal handle drag-to-select and its native clipboard.
            mouse_support=False,
        )


def run_tui(provider: LLMProvider | None, db_url: str, ctx_obj: dict | None = None):
    """Entry point for running the TUI.

    Resolves the session agent before taking over the screen: the default
    assistant's saved provider/model wins, so restarts never re-ask. Only when
    there is nothing saved yet do we prompt (and then persist the answer).
    """
    from hobees.cli.shell import get_assistant_selection, persist_assistant_selection

    model_name: str | None = None
    assistant_provider, assistant_model = get_assistant_selection()

    if provider is None and assistant_provider is not None:
        provider = assistant_provider
        model_name = assistant_model or provider.default_model
    elif provider is None:
        from hobees.db.session import session_scope
        from hobees.db.models import LLMProvider
        from hobees.core.model_discovery import fetch_provider_models
        from hobees.cli.provider_cmd import interactive_model_picker
        from hobees.cli.icons import APP, SUCCESS
        from rich.console import Console
        from rich.prompt import Prompt, Confirm

        console = Console()

        with session_scope() as session:
            providers = session.query(LLMProvider).order_by(LLMProvider.id).all()

        if len(providers) == 1:
            provider = providers[0]
        elif len(providers) > 1:
            console.print(f"{APP} hobees Interactive Shell")
            console.print("No default assistant configured yet. Please select its provider:")
            for i, p in enumerate(providers, 1):
                console.print(f"  [cyan]({i})[/cyan] {p.alias} ({p.provider_type}) - default: {p.default_model or 'none'}")

            choice = Prompt.ask("Select provider", choices=[str(i) for i in range(1, len(providers) + 1)])
            provider = providers[int(choice) - 1]

        if provider is not None:
            model_name = provider.default_model
            if not model_name:
                models = fetch_provider_models(provider, refresh_cache=False)
                if len(models) == 1:
                    model_name = models[0]
                elif models:
                    console.print(f"\nAvailable models for {provider.alias}:")
                    model_name = interactive_model_picker(models, default=None)

    if provider is not None:
        from hobees.db.session import session_scope

        model_name = model_name or provider.default_model
        persist_assistant_selection(provider.id, model_name)
        with session_scope() as session:
            refreshed = session.get(type(provider), provider.id)
            if refreshed is not None:
                provider = refreshed

    tui = HobeesTUI()
    tui.run(provider, db_url, ctx_obj, model_name=model_name)