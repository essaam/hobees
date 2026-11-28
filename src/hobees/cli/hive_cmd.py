"""Working Hive handlers — shared by the Typer CLI (`hobees hive ...`) and the
interactive shell slash commands (`/hive ...`).

Hives group existing Bees under a Hive Supervisor. Bees and Hives have a
many-to-many relationship via ``hive_memberships``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from hobees.cli.icons import BEE, ERROR, HIVE, SKILL, SUCCESS, WARN
from hobees.cli.provider_cmd import interactive_model_picker

console = Console()

app = typer.Typer(name="hive", help="Manage Working Hives (Bee teams)")

# ---------------------------------------------------------------------------
# handlers (shared with shell.py)
# ---------------------------------------------------------------------------

def get_hive_artifacts_dir(hive_name: str) -> Path:
    """Return a hive's configured project directory or its default artifacts directory."""
    from hobees.config import settings
    from hobees.db.models import Hive
    from hobees.db.session import session_scope

    with session_scope() as session:
        hive = session.query(Hive).filter_by(name=hive_name).first()
        project_path = hive.project_path if hive else None

    if project_path:
        return Path(project_path).expanduser()
    return settings.artifacts_root / hive_name


def _get_id(session, model, **filters):
    row = session.query(model).filter_by(**filters).first()
    if not row:
        raise KeyError(filters)
    return row.id


def cmd_hive_create(
    name: str,
    goal_description: str | None = None,
    supervisor_provider_id: int | None = None,
    supervisor_model_name: str = "gpt-4o-mini",
    supervisor_prompt: str | None = None,
    is_dynamic: bool = False,
    supervisor_thinking_level: str = "medium",
    project_path: str | None = None,
) -> None:
    """Create a new Working Hive backed by a Hive Supervisor."""
    from hobees.db.session import session_scope
    from hobees.db.models import Hive, LLMProvider
    from hobees.core.model_discovery import fetch_provider_models
    from pathlib import Path

    if supervisor_provider_id is None:
        console.print(f"{ERROR} supervisor_provider_id is required")
        raise typer.Exit(code=1)
    with session_scope() as session:
        provider = session.get(LLMProvider, supervisor_provider_id)
        if not provider:
            console.print(f"{ERROR} provider id {supervisor_provider_id} not found")
            raise typer.Exit(code=1)
        if session.query(Hive).filter_by(name=name).first():
            console.print(f"{ERROR} Hive {name!r} already exists")
            raise typer.Exit(code=1)

        # Interactive model picker if available
        if provider and supervisor_model_name:
            models = fetch_provider_models(provider, refresh_cache=False)
            if models:
                selected = interactive_model_picker(models, default=supervisor_model_name)
                if selected is not None:
                    supervisor_model_name = selected

        # Create project subdirectory if project_path is provided
        if project_path:
            path = Path(project_path).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            console.print(f"{SUCCESS} Created project directory: {path}")

        hive = Hive(
            name=name,
            goal_description=goal_description,
            supervisor_provider_id=supervisor_provider_id,
            supervisor_model_name=supervisor_model_name,
            supervisor_prompt=supervisor_prompt,
            supervisor_thinking_level=supervisor_thinking_level,
            is_dynamic=is_dynamic,
            project_path=project_path,
        )
        session.add(hive)
        session.flush()
        hive_id = hive.id
    tag = "dynamic" if is_dynamic else "static"
    console.print(
        f"{SUCCESS} Hive {name!r} created ({tag}, id={hive_id}, "
        f"supervisor={provider.alias}/{supervisor_model_name}, thinking={supervisor_thinking_level})"
    )


def cmd_hive_add_bee(hive_name: str, bee_name: str) -> None:
    """Assign an existing Bee to a Hive."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, Hive, HiveMembership

    with session_scope() as session:
        hive = session.query(Hive).filter_by(name=hive_name).first()
        if not hive:
            console.print(f"{ERROR} Hive {hive_name!r} not found")
            raise typer.Exit(code=1)
        bee = session.query(Bee).filter_by(name=bee_name).first()
        if not bee:
            console.print(f"{ERROR} Bee {bee_name!r} not found")
            raise typer.Exit(code=1)
        exists = (
            session.query(HiveMembership)
            .filter_by(hive_id=hive.id, bee_id=bee.id)
            .first()
        )
        if exists:
            console.print(f"{WARN} Bee {bee_name!r} already in Hive {hive_name!r}")
            return
        session.add(HiveMembership(hive_id=hive.id, bee_id=bee.id))
    console.print(f"{SUCCESS} Bee {bee_name!r} added to Hive {hive_name!r}.")


def cmd_hive_remove_bee(hive_name: str, bee_name: str) -> None:
    """Remove a Bee from a Hive (the Bee itself is not deleted)."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, Hive, HiveMembership

    with session_scope() as session:
        hive = session.query(Hive).filter_by(name=hive_name).first()
        if not hive:
            console.print(f"{ERROR} Hive {hive_name!r} not found")
            raise typer.Exit(code=1)
        bee = session.query(Bee).filter_by(name=bee_name).first()
        if not bee:
            console.print(f"{ERROR} Bee {bee_name!r} not found")
            raise typer.Exit(code=1)
        deleted = (
            session.query(HiveMembership)
            .filter_by(hive_id=hive.id, bee_id=bee.id)
            .delete()
        )
    if deleted:
        console.print(f"{SUCCESS} Bee {bee_name!r} removed from Hive {hive_name!r}.")
    else:
        console.print(f"{WARN} Bee {bee_name!r} was not in Hive {hive_name!r}.")


def cmd_hive_list() -> None:
    """List Hives with supervisor and member counts."""
    from hobees.db.session import session_scope
    from hobees.db.models import Hive

    with session_scope() as session:
        rows = [
            (
                h.name,
                f"{h.supervisor_provider.alias}/{h.supervisor_model_name}",
                h.supervisor_thinking_level,
                len(h.memberships),
                "dynamic" if h.is_dynamic else "static",
                h.project_path or "-",
            )
            for h in session.query(Hive).order_by(Hive.name).all()
        ]

    table = Table(title="Working Hives")
    table.add_column("name", style="cyan")
    table.add_column("supervisor", style="green")
    table.add_column("thinking")
    table.add_column("members")
    table.add_column("type")
    table.add_column("project path")

    for name, supervisor, thinking, member_count, hive_type, project_path in rows:
        table.add_row(
            name,
            supervisor,
            thinking,
            str(member_count),
            hive_type,
            project_path,
        )
    if not rows:
        console.print(f"{WARN} No Hives yet. Use /hive create.")
    else:
        console.print(table)


def get_hive_names() -> list[str]:
    """Return registered hive names in the order used by numbered pickers."""
    from hobees.db.session import session_scope
    from hobees.db.models import Hive

    with session_scope() as session:
        return [
            name
            for (name,) in session.query(Hive.name).order_by(Hive.name).all()
        ]


def resolve_hive_selection(selection: str, hive_names: list[str]) -> list[str]:
    """Resolve comma- or whitespace-separated 1-based hive numbers."""
    tokens = selection.replace(",", " ").split()
    if not tokens:
        raise ValueError("Select at least one hive number.")

    indices = []
    for token in tokens:
        if not token.isdecimal():
            raise ValueError(f"{token!r} is not a hive number.")
        index = int(token)
        if index < 1 or index > len(hive_names):
            raise ValueError(f"Hive number {index} is out of range.")
        if index not in indices:
            indices.append(index)
    return [hive_names[index - 1] for index in indices]


def remove_hives(names: list[str]) -> list[str]:
    """Delete the named hives while preserving their bees and run history."""
    from hobees.db.session import session_scope
    from hobees.db.models import Hive, HiveMembership, Run

    requested = list(dict.fromkeys(names))
    if not requested:
        raise ValueError("Specify at least one hive to remove.")

    with session_scope() as session:
        hives = session.query(Hive).filter(Hive.name.in_(requested)).all()
        found = {hive.name for hive in hives}
        missing = [name for name in requested if name not in found]
        if missing:
            raise ValueError(f"Hive(s) not found: {', '.join(missing)}")

        hive_ids = [hive.id for hive in hives]
        session.query(HiveMembership).filter(
            HiveMembership.hive_id.in_(hive_ids)
        ).delete(synchronize_session=False)
        session.query(Run).filter(Run.hive_id.in_(hive_ids)).update(
            {Run.hive_id: None}, synchronize_session=False
        )
        for hive in hives:
            session.delete(hive)

    return requested


def cmd_hive_remove(names: list[str]) -> None:
    """Remove named hives without deleting their bees or run history."""
    try:
        removed = remove_hives(names)
    except ValueError as exc:
        console.print(f"{ERROR} {exc}")
        raise typer.Exit(code=1) from exc
    for name in removed:
        console.print(f"{SUCCESS} Hive {name!r} removed.")


def cmd_hive_remove_interactive(selection: str | None = None) -> None:
    """Show numbered hives and interactively remove one or more selections."""
    from rich.prompt import Confirm, Prompt

    hive_names = get_hive_names()
    if not hive_names:
        console.print(f"{WARN} No Hives to remove.")
        return

    table = Table(title="Working Hives")
    table.add_column("#", style="dim", justify="right")
    table.add_column("name", style="cyan")
    for index, name in enumerate(hive_names, 1):
        table.add_row(str(index), name)
    console.print(table)

    while selection is None:
        answer = Prompt.ask(
            "Hive numbers to remove (comma-separated; q to cancel)"
        ).strip()
        if answer.lower() in ("q", "quit", "cancel"):
            console.print(f"{WARN} Hive removal cancelled.")
            return
        try:
            selected = resolve_hive_selection(answer, hive_names)
        except ValueError as exc:
            console.print(f"{ERROR} {exc}")
            continue
        break
    else:
        try:
            selected = resolve_hive_selection(selection, hive_names)
        except ValueError as exc:
            console.print(f"{ERROR} {exc}")
            raise typer.Exit(code=1) from exc

    if not Confirm.ask(
        f"Remove {len(selected)} hive(s): {', '.join(selected)}?", default=False
    ):
        console.print(f"{WARN} Hive removal cancelled.")
        return
    cmd_hive_remove(selected)


def cmd_hive_thinking(name: str, level: str) -> None:
    """Set a Hive Supervisor's default thinking level."""
    from hobees.db.session import session_scope
    from hobees.db.models import Hive

    valid_levels = ("off", "low", "medium", "high")
    if level not in valid_levels:
        console.print(f"{ERROR} thinking level must be one of {valid_levels}")
        raise typer.Exit(code=1)

    with session_scope() as session:
        hive = session.query(Hive).filter_by(name=name).first()
        if not hive:
            console.print(f"{ERROR} Hive {name!r} not found")
            raise typer.Exit(code=1)
        hive.supervisor_thinking_level = level
    console.print(f"{SUCCESS} Hive {name!r} supervisor thinking level set to '{level}'")


def cmd_hive_run(
    hive_name: str,
    goal: str,
    thread_id: str | None = None,
    output_json: bool = False,
    quiet: bool = False,
    timeout: int | None = None,
    artifacts_dir: str | None = None,
    thinking: str | None = None,
    approval_mode: str | None = None,
    container_name: str | None = None,
    resume_decision: str | None = None,
    resume_args: str | None = None,
    resume_reason: str | None = None,
    replay: str | None = None,
    patch_message: str | None = None,
) -> None:
    """Execute a goal non-interactively using a specific Hive (headless / CI/CD mode)."""
    import json
    import sys
    import uuid
    import asyncio
    from datetime import datetime, timezone
    from pathlib import Path

    from hobees.db.session import get_engine, session_scope
    from hobees.db.models import Hive, LLMProvider, Run
    from hobees.core.hive_builder import hive_app_async
    from hobees.core.tracing import write_run_manifest
    from hobees.db.analytics import run_thread_usage
    from hobees.config import settings
    from hobees.core.approval import (
        resolve_approval_mode,
        resolve_container_name,
        resolve_thread_id,
    )

    container_name = resolve_container_name(container_name)
    approval_mode = resolve_approval_mode(
        approval_mode,
        interactive=sys.stdin.isatty(),
    )
    if approval_mode not in {"interactive", "auto", "strict", "pause"}:
        console.print(f"{ERROR} Invalid approval mode: {approval_mode}")
        raise typer.Exit(code=1)
    if resume_decision and resume_decision not in {"approve", "edit", "reject"}:
        console.print(f"{ERROR} Invalid resume decision: {resume_decision}")
        raise typer.Exit(code=1)


    with session_scope() as session:
        hive = session.query(Hive).filter_by(name=hive_name).first()
        if not hive:
            console.print(f"{ERROR} Hive {hive_name!r} not found")
            raise typer.Exit(code=1)

        bees = [m.bee for m in hive.memberships if m.bee]
        if not bees:
            console.print(f"{ERROR} Hive {hive_name!r} has no member bees. Add bees first.")
            raise typer.Exit(code=1)

        provider_ids = {b.provider_id for b in bees} | {hive.supervisor_provider_id}
        providers = {
            p.id: p for p in session.query(LLMProvider).filter(LLMProvider.id.in_(provider_ids)).all()
        }

    thread_id = resolve_thread_id(
        "hive",
        hive.name,
        user_thread=thread_id,
        container_name=container_name,
    )

    # Determine artifacts directory
    if artifacts_dir:
        art_path = Path(artifacts_dir)
    elif hive.project_path:
        art_path = Path(hive.project_path)
    else:
        art_path = settings.artifacts_root / hive.name

    art_path.mkdir(parents=True, exist_ok=True)

    if not output_json and not quiet:
        console.print(f"{HIVE} [bold]Activating Hive: {hive.name}[/bold]")
        console.print(f"  Goal: {goal}")
        console.print(f"  Thread ID: {thread_id}")
        console.print(f"  Artifacts: {art_path.resolve()}")
        console.print(f"  Workers: {', '.join(b.name for b in bees)}")
        console.print()

    start_time = datetime.now(timezone.utc)
    with session_scope() as session:
        run = session.query(Run).filter_by(thread_id=thread_id).first()
        if run and run.hive_id not in (None, hive.id):
            console.print(
                f"{ERROR} Thread {thread_id!r} belongs to a different hive."
            )
            raise typer.Exit(code=1)
        if run:
            run.hive_id = hive.id
            run.container_name = container_name
            run.mode = "targeted"
            run.goal = goal
            run.status = "running"
            run.artifacts_dir = str(art_path.resolve())
            run.started_at = start_time
            run.completed_at = None
            run.suggested_skill_draft = None
        else:
            run = Run(
                thread_id=thread_id,
                container_name=container_name,
                hive_id=hive.id,
                mode="targeted",
                goal=goal,
                status="running",
                artifacts_dir=str(art_path.resolve()),
            )
            session.add(run)
            session.flush()
        run_id = run.id

    engine = get_engine()
    db_url = engine.url
    output_text = ""
    skill_draft = None
    error_msg = None
    broker = None
    event_queue = None
    if not output_json and not quiet:
        from hobees.core.tracing import EventBroker

        broker = EventBroker.get_instance()

    try:
        async def _run_hive():
            nonlocal event_queue

            async with hive_app_async(
                hive,
                bees,
                providers,
                db_url,
                thread_id,
                run_id,
                thinking,
                artifact_root=art_path,
                approval_mode=approval_mode,
                container_name=container_name,
            ) as app:
                if broker is not None:
                    event_queue = broker.subscribe()
                from langgraph.types import Command

                if replay:
                    replay_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_id": replay,
                        }
                    }
                    replay_found = False
                    async for state in app.aget_state_history(
                        {"configurable": {"thread_id": thread_id}}
                    ):
                        if getattr(state, "config", {}).get("configurable", {}).get(
                            "checkpoint_id"
                        ) == replay:
                            replay_found = True
                            break
                    if not replay_found:
                        raise RuntimeError(
                            f"Checkpoint {replay!r} was not found for thread {thread_id}"
                        )
                    if patch_message:
                        await app.aupdate_state(
                            replay_config,
                            {"messages": [("user", patch_message)]},
                        )
                    invoke_input = None
                    invoke_config = replay_config
                elif resume_decision:
                    resume_payload = {"action": resume_decision}
                    if resume_decision == "edit" and resume_args:
                        resume_payload["args"] = json.loads(resume_args)
                    if resume_decision == "reject":
                        resume_payload["reason"] = resume_reason or "Rejected by operator."
                    invoke_input = Command(resume=resume_payload)
                    invoke_config = {"configurable": {"thread_id": thread_id}}
                else:
                    invoke_input = {"messages": [("user", goal)]}
                    invoke_config = {"configurable": {"thread_id": thread_id}}

                invoke_task = asyncio.create_task(
                    app.ainvoke(
                        invoke_input,
                        config=invoke_config,
                    )
                )
                try:
                    while event_queue is not None and not invoke_task.done():
                        try:
                            event = await asyncio.wait_for(event_queue.get(), timeout=0.25)
                        except asyncio.TimeoutError:
                            continue
                        if event.get("thread_id") == thread_id:
                            event_type = event.get("event_type", "")
                            source = event.get("source", "")
                            target = event.get("target", "")
                            console.print(
                                f"[dim][{event_type}] {source}"
                                f"{f' -> {target}' if target else ''}[/dim]"
                            )
                    return await invoke_task
                finally:
                    if not invoke_task.done():
                        invoke_task.cancel()
                        try:
                            await invoke_task
                        except asyncio.CancelledError:
                            pass

        if timeout:
            result = asyncio.run(asyncio.wait_for(_run_hive(), timeout=timeout))
        else:
            result = asyncio.run(_run_hive())

        interrupts = result.get("__interrupt__", []) if isinstance(result, dict) else []
        awaiting_approval = bool(interrupts)

        if awaiting_approval and approval_mode == "interactive":
            async def _resume_interruptively():
                from langgraph.types import Command

                async with hive_app_async(
                    hive, bees, providers, db_url, thread_id, run_id, thinking,
                    artifact_root=art_path,
                    approval_mode=approval_mode,
                    container_name=container_name,
                ) as app:
                    current = result
                    while current.get("__interrupt__", []) if isinstance(current, dict) else []:
                        interrupt_items = current.get("__interrupt__", [])
                        if not interrupt_items:
                            break
                        item = interrupt_items[0]
                        payload = getattr(item, "value", None) or item
                        console.print(
                            f"\n[bold yellow]Approval required[/bold yellow] "
                            f"bee={payload.get('bee')} tool={payload.get('tool')}"
                        )
                        console.print_json(data=payload.get("args", {}))
                        choice = console.input("[A]pprove / [E]dit / [R]eject: ").strip().lower()
                        if choice.startswith("e"):
                            import json as json_module
                            edited = console.input("JSON args: ").strip()
                            decision = {
                                "action": "edit",
                                "args": json_module.loads(edited),
                            }
                        elif choice.startswith("r"):
                            decision = {
                                "action": "reject",
                                "reason": console.input("Reason (optional): ").strip()
                                or "Rejected by operator.",
                            }
                        else:
                            decision = {"action": "approve"}
                        current = await app.ainvoke(
                            Command(resume=decision),
                            config={"configurable": {"thread_id": thread_id}},
                        )
                    return current

            result = asyncio.run(_resume_interruptively())
            interrupts = result.get("__interrupt__", []) if isinstance(result, dict) else []
            awaiting_approval = bool(interrupts)

        msgs = result.get("messages", []) if isinstance(result, dict) else []
        if msgs:
            last = msgs[-1]
            output_text = str(getattr(last, "content", last))
        else:
            output_text = str(result)

        completed_at = datetime.now(timezone.utc)
        duration_sec = round((completed_at - start_time).total_seconds(), 2)

        with session_scope() as session:
            run_obj = session.get(Run, run_id)
            if run_obj:
                run_obj.status = (
                    "awaiting_approval"
                    if awaiting_approval
                    else "completed"
                )
                run_obj.completed_at = completed_at
        if not awaiting_approval:
            from hobees.core.memory_manager import extract_run_memories

            extract_run_memories(
                goal=goal,
                output=output_text,
                provider=providers[hive.supervisor_provider_id],
                model_name=hive.supervisor_model_name,
                hive_name=hive.name,
                source_thread_id=thread_id,
                allow_hive_facts=not hive.is_dynamic,
            )
            from hobees.core.skill_harvester import harvest_completed_run

            skill_draft = harvest_completed_run(run_id)

    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        duration_sec = round((completed_at - start_time).total_seconds(), 2)
        error_msg = str(exc) or (
            f"Timed out after {timeout} seconds"
            if isinstance(exc, asyncio.TimeoutError) and timeout
            else type(exc).__name__
        )
        with session_scope() as session:
            run_obj = session.get(Run, run_id)
            if run_obj:
                run_obj.status = "failed"
                run_obj.completed_at = completed_at
    finally:
        if broker is not None and event_queue is not None:
            broker.unsubscribe(event_queue)

    from hobees.core.pipeline_status import pipeline_exit_code

    final_status = "failed" if error_msg else ("awaiting_approval" if awaiting_approval else "completed")
    # Build and write manifest
    usage = run_thread_usage(thread_id) or {}
    manifest_data = {
        "run_id": run_id,
        "container": container_name,
        "thread_id": thread_id,
        "thread": thread_id,
        "hive_name": hive.name,
        "goal": goal,
        "status": final_status,
        "error": error_msg,
        "exit_code": pipeline_exit_code(final_status),
        "started_at": start_time.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": duration_sec,
        "artifacts_dir": str(art_path.resolve()),
        "output": output_text,
        "usage": usage,
        "suggested_skill_draft": skill_draft,
    }
    if awaiting_approval:
        manifest_data["pending_approvals"] = []
        for item in interrupts:
            payload = getattr(item, "value", None) or (
                item.get("value") if isinstance(item, dict) else item
            )
            if isinstance(payload, dict):
                manifest_data["pending_approvals"].append({
                    "bee": payload.get("bee"),
                    "tool": payload.get("tool"),
                    "tool_call_id": payload.get("tool_call_id"),
                    "args": payload.get("args", {}),
                })
    write_run_manifest(art_path, manifest_data)

    if output_json:
        console.print(json.dumps(manifest_data, indent=2), markup=False)
    elif not quiet:
        if error_msg:
            console.print(f"\n{ERROR} Hive run failed: {error_msg}")
        else:
            console.print(f"\n{SUCCESS} [bold]Hive {hive.name} completed successfully[/bold]")
            console.print(f"\n{output_text}\n")
            if skill_draft:
                console.print(
                    f"{SKILL} Skill draft {skill_draft['name']!r} generated; "
                    "review and save it with 'hobees skill save-last'."
                )
            if usage:
                events = usage.get("events", 0)
                in_toks = usage.get("input_tokens", 0) or 0
                out_toks = usage.get("output_tokens", 0) or 0
                cost = usage.get("estimated_cost_usd", 0.0) or 0.0
                console.print(
                    f"[dim]📊 Telemetry: {in_toks:,} in / {out_toks:,} out tokens • ${cost:.4f} • {events} LLM steps[/dim]"
                )
            console.print(f"[dim]📁 Artifacts & manifest saved to: {art_path.resolve()}[/dim]")
    elif error_msg:
        Console(stderr=True).print(error_msg)
    else:
        console.print(output_text, markup=False)

    # The pipeline reads this code: 0 completed, 1 failed, 2 stopped for an approval a
    # headless run cannot answer. A run that stops for approval is not a success, so it
    # must not exit 0.
    code = pipeline_exit_code(final_status)
    if code:
        raise typer.Exit(code=code)


# ---------------------------------------------------------------------------
# Typer CLI commands
# ---------------------------------------------------------------------------


@app.command(name="create")
def cli_create(
    name: Annotated[str, typer.Argument(help="Unique Hive name")],
    supervisor_provider_id: Annotated[
        int, typer.Argument(help="Registered LLM provider id for the Hive Supervisor")
    ],
    goal_description: Annotated[str | None, typer.Option("--goal")] = None,
    supervisor_model_name: Annotated[str, typer.Option("--supervisor-model")] = "gpt-4o-mini",
    supervisor_prompt: Annotated[str | None, typer.Option("--supervisor-prompt")] = None,
    is_dynamic: Annotated[bool, typer.Option("--dynamic/--static")] = False,
    supervisor_thinking_level: Annotated[str, typer.Option("--thinking", help="off | low | medium | high")] = "medium",
    project_path: Annotated[str | None, typer.Option("--project-path", help="Project subdirectory path (relative to project root)")] = None,
) -> None:
    cmd_hive_create(
        name, goal_description, supervisor_provider_id, supervisor_model_name,
        supervisor_prompt, is_dynamic, supervisor_thinking_level, project_path,
    )


@app.command(name="add-bee")
def cli_add_bee(
    hive_name: Annotated[str, typer.Argument(help="Hive name")],
    bee_name: Annotated[str, typer.Argument(help="Bee name")],
) -> None:
    cmd_hive_add_bee(hive_name, bee_name)


@app.command(name="remove-bee")
def cli_remove_bee(
    hive_name: Annotated[str, typer.Argument(help="Hive name")],
    bee_name: Annotated[str, typer.Argument(help="Bee name")],
) -> None:
    cmd_hive_remove_bee(hive_name, bee_name)


@app.command(name="list")
def cli_list() -> None:
    cmd_hive_list()


@app.command(name="remove")
def cli_remove(
    names: Annotated[
        list[str] | None,
        typer.Argument(help="Hive names to remove (required in headless mode)"),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation")
    ] = False,
) -> None:
    """Remove one or more Hives; without names, open the interactive picker.

    Hives declared in the configured import file may be recreated by a later
    config sync, so remove them from that file as well.
    """
    import sys
    from rich.prompt import Confirm

    if not names:
        if not sys.stdin.isatty():
            console.print(
                f"{ERROR} Provide hive names in headless mode, e.g. "
                "'hobees hive remove my-hive --yes'."
            )
            raise typer.Exit(code=1)
        cmd_hive_remove_interactive()
        return

    if not yes and sys.stdin.isatty() and not Confirm.ask(
        f"Remove {len(set(names))} hive(s): {', '.join(dict.fromkeys(names))}?",
        default=False,
    ):
        console.print(f"{WARN} Hive removal cancelled.")
        return
    cmd_hive_remove(names)


@app.command(name="thinking")
def cli_thinking(
    name: Annotated[str, typer.Argument(help="Hive name")],
    level: Annotated[str, typer.Argument(help="off | low | medium | high")],
) -> None:
    cmd_hive_thinking(name, level)


@app.command(name="run")
def cli_run(
    hive_name: Annotated[str, typer.Argument(help="Hive name to activate")],
    goal: Annotated[
        str | None,
        typer.Argument(help="Task/goal instruction, `-` to read stdin, or omit with --goal-file"),
    ] = None,
    thread_id: Annotated[str | None, typer.Option("--thread", "-t", help="Thread ID to attach/resume")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output run results as structured JSON to stdout")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Minimal output, suppress banners")] = False,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Maximum execution timeout in seconds")] = None,
    artifacts_dir: Annotated[str | None, typer.Option("--artifacts-dir", help="Directory where hive outputs land")] = None,
    thinking: Annotated[str | None, typer.Option("--thinking", help="Session thinking level override: off|low|medium|high")] = None,
    approval_mode: Annotated[str | None, typer.Option("--approval-mode", help="interactive|auto|strict|pause")] = None,
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Convenience alias for --approval-mode auto")] = False,
    container_name: Annotated[str | None, typer.Option("--container", help="Container/instance name")] = None,
    resume_decision: Annotated[str | None, typer.Option("--resume-decision", help="approve|edit|reject")] = None,
    resume_args: Annotated[str | None, typer.Option("--resume-args", help="JSON arguments for edit decisions")] = None,
    resume_reason: Annotated[str | None, typer.Option("--resume-reason", help="Reason for reject decisions")] = None,
    replay: Annotated[str | None, typer.Option("--replay", help="Replay from a LangGraph checkpoint ID")] = None,
    patch_message: Annotated[str | None, typer.Option("--patch-message", help="Patch replay state with a human message")] = None,
    goal_file: Annotated[
        str | None,
        typer.Option("--goal-file", help="Read the goal from a file (or - for stdin)"),
    ] = None,
) -> None:
    """Execute a goal non-interactively using a Hive (headless / CI/CD mode).

    The goal can be a long prompt, so it may also come from a file or stdin:
    `hobees hive run dev-team --goal-file goal.txt`, `hobees hive run dev-team - < goal.txt`.
    """
    from hobees.cli.goal_input import require_goal, resolve_goal

    cmd_hive_run(
        hive_name=hive_name,
        goal=require_goal(resolve_goal(goal, goal_file)),
        thread_id=thread_id,
        output_json=output_json,
        quiet=quiet,
        timeout=timeout,
        artifacts_dir=artifacts_dir,
        thinking=thinking,
        approval_mode="auto" if auto_approve else approval_mode,
        container_name=container_name,
        resume_decision=resume_decision,
        resume_args=resume_args,
        resume_reason=resume_reason,
        replay=replay,
        patch_message=patch_message,
    )


__all__ = [
    "app",
    "cmd_hive_create",
    "cmd_hive_add_bee",
    "cmd_hive_remove_bee",
    "cmd_hive_list",
    "cmd_hive_thinking",
    "cmd_hive_run",
    "get_hive_artifacts_dir",
]