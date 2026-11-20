"""Skill management handlers — shared by the Typer CLI (`hobees skill ...`)
and the interactive shell slash commands (`/skill ...`).

Progressive skill library with bi-directional Markdown sync.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from hobees.cli.icons import ERROR, SKILL, SUCCESS, WARN
from hobees.core.skill_harvester import persist_skill, sync_skills_from_markdown
from hobees.db.session import session_scope
from hobees.db.models import Skill, Bee, BeeSkill

console = Console()

app = typer.Typer(name="skill", help="Progressive skill library")


def cmd_skill_list() -> None:
    """List all saved skills."""
    with session_scope() as session:
        skills = session.query(Skill).order_by(Skill.name).all()

    if not skills:
        console.print(f"{WARN} No skills registered yet. Use /skill create.")
        return

    table = Table(title="Skill Library")
    table.add_column("name", style="cyan")
    table.add_column("description")
    table.add_column("usage", style="dim")
    table.add_column("bees")
    for s in skills:
        bee_names = ", ".join(b.name for b in s.bees) or "-"
        table.add_row(s.name, s.description, str(s.usage_count), bee_names)
    console.print(table)


def cmd_skill_show(name: str) -> None:
    """Show full skill instructions."""
    with session_scope() as session:
        skill = session.query(Skill).filter_by(name=name).first()
    if not skill:
        console.print(f"{ERROR} Skill {name!r} not found")
        raise typer.Exit(code=1)

    console.print(f"[bold]{skill.name}[/bold]")
    console.print(f"Description: {skill.description}")
    console.print(f"Tags: {', '.join(skill.tags) or '-'}")
    console.print(f"Usage count: {skill.usage_count}")
    console.print(f"Bees: {', '.join(b.name for b in skill.bees) or '-'}")
    console.print("\n[bold]Instructions:[/bold]")
    console.print(skill.instructions)


def cmd_skill_create(
    name: str | None = None,
    description: str | None = None,
    instructions: str | None = None,
    tags: str = "",
    from_file: str | None = None,
) -> None:
    """Create a new skill interactively or from file."""
    if from_file:
        from pathlib import Path
        path = Path(from_file).expanduser()
        if not path.exists():
            console.print(f"{ERROR} File not found: {path}")
            raise typer.Exit(code=1)
        content = path.read_text(encoding="utf-8")
        # Parse name from first # heading
        for line in content.split("\n"):
            if line.startswith("# "):
                name = line[2:].strip()
                break
        else:
            name = path.stem
        description = f"Imported from {path.name}"
        instructions = content
        tags = ""
    else:
        # Interactive wizard
        console.print("[bold]Skill Creation Wizard[/bold]")
        name = name or Prompt.ask("Skill name (kebab-case)")
        description = description or Prompt.ask("One-line description")
        console.print("Enter instructions (Markdown). End with Ctrl+D / Ctrl+Z:")
        import sys
        instructions = instructions or sys.stdin.read()
        tags = tags or Prompt.ask("Tags (comma-separated)", default="")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    with session_scope() as session:
        if session.query(Skill).filter_by(name=name).first():
            console.print(f"{ERROR} Skill {name!r} already exists")
            raise typer.Exit(code=1)
        skill = Skill(
            name=name,
            description=description,
            instructions=instructions,
            tags=tag_list,
        )
        session.add(skill)

    # Write Markdown file
    from hobees.config import settings
    md_path = settings.skills_dir / f"{name}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_content = f"""# {name}

**Description:** {description}

**Tags:** {", ".join(tag_list)}

---

{instructions}
"""
    md_path.write_text(md_content, encoding="utf-8")

    console.print(f"{SUCCESS} Skill {name!r} created and saved to {md_path}")


def cmd_skill_save_last() -> None:
    """Persist the skill draft from the most recent run."""
    from hobees.db.models import Run

    with session_scope() as session:
        run = (
            session.query(Run)
            .filter(Run.suggested_skill_draft.is_not(None))
            .order_by(Run.completed_at.desc().nullslast())
            .first()
        )
    if not run or not run.suggested_skill_draft:
        console.print(f"{WARN} No skill draft found from recent runs.")
        return

    draft = run.suggested_skill_draft
    console.print(f"[bold]Draft skill:[/bold] {draft.get('name', 'unnamed')}")
    console.print(f"Description: {draft.get('description', '')}")
    console.print("\nOptions: [y] save as-is, [e] edit first, [n] cancel")
    choice = Prompt.ask("Choice", choices=["y", "e", "n"], default="y")

    if choice == "n":
        console.print("Cancelled.")
        return
    elif choice == "e":
        # Allow editing description and instructions
        draft["description"] = Prompt.ask("Description", default=draft.get("description", ""))
        console.print("Enter instructions (Markdown). End with Ctrl+D / Ctrl+Z:")
        import sys
        draft["instructions"] = sys.stdin.read() or draft.get("instructions", "")

    skill = persist_skill(draft, run.thread_id)
    console.print(f"{SUCCESS} Skill {skill.name!r} saved and linked to {len(skill.bees)} bee(s).")


def cmd_skill_assign(skill_name: str, bee_name: str) -> None:
    """Link an existing skill to a Bee."""
    with session_scope() as session:
        skill = session.query(Skill).filter_by(name=skill_name).first()
        if not skill:
            console.print(f"{ERROR} Skill {skill_name!r} not found")
            raise typer.Exit(code=1)
        bee = session.query(Bee).filter_by(name=bee_name).first()
        if not bee:
            console.print(f"{ERROR} Bee {bee_name!r} not found")
            raise typer.Exit(code=1)

        # Check if already linked
        existing = session.query(BeeSkill).filter_by(bee_id=bee.id, skill_id=skill.id).first()
        if existing:
            console.print(f"{WARN} Skill {skill_name!r} already assigned to Bee {bee_name!r}")
            return

        session.add(BeeSkill(bee_id=bee.id, skill_id=skill.id))
    console.print(f"{SUCCESS} Skill {skill_name!r} assigned to Bee {bee_name!r}")


def cmd_skill_unassign(skill_name: str, bee_name: str) -> None:
    """Remove a skill from a Bee."""
    with session_scope() as session:
        skill = session.query(Skill).filter_by(name=skill_name).first()
        if not skill:
            console.print(f"{ERROR} Skill {skill_name!r} not found")
            raise typer.Exit(code=1)
        bee = session.query(Bee).filter_by(name=bee_name).first()
        if not bee:
            console.print(f"{ERROR} Bee {bee_name!r} not found")
            raise typer.Exit(code=1)

        deleted = session.query(BeeSkill).filter_by(bee_id=bee.id, skill_id=skill.id).delete()
        if deleted:
            console.print(f"{SUCCESS} Skill {skill_name!r} unassigned from Bee {bee_name!r}")
        else:
            console.print(f"{WARN} Skill was not assigned to that Bee")


def cmd_skill_sync() -> None:
    """Sync skills from ~/.hobees/skills/*.md files."""
    count = sync_skills_from_markdown()
    console.print(f"{SUCCESS} Synced {count} new skill(s) from Markdown files.")


# ---------------------------------------------------------------------------
# Typer CLI commands
# ---------------------------------------------------------------------------


@app.command(name="list")
def cli_list() -> None:
    cmd_skill_list()


@app.command(name="show")
def cli_show(name: Annotated[str, typer.Argument(help="Skill name")]) -> None:
    cmd_skill_show(name)


@app.command(name="create")
def cli_create(
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    instructions: Annotated[str | None, typer.Option("--instructions")] = None,
    tags: Annotated[str, typer.Option("--tags")] = "",
    from_file: Annotated[str | None, typer.Option("--from-file", help="Import from Markdown file")] = None,
) -> None:
    cmd_skill_create(name, description, instructions, tags, from_file)


@app.command(name="save-last")
def cli_save_last() -> None:
    cmd_skill_save_last()


@app.command(name="assign")
def cli_assign(
    skill_name: Annotated[str, typer.Argument(help="Skill name")],
    bee_name: Annotated[str, typer.Argument(help="Bee name")],
) -> None:
    cmd_skill_assign(skill_name, bee_name)


@app.command(name="unassign")
def cli_unassign(
    skill_name: Annotated[str, typer.Argument(help="Skill name")],
    bee_name: Annotated[str, typer.Argument(help="Bee name")],
) -> None:
    cmd_skill_unassign(skill_name, bee_name)


@app.command(name="sync")
def cli_sync() -> None:
    cmd_skill_sync()


__all__ = [
    "app",
    "cmd_skill_list",
    "cmd_skill_show",
    "cmd_skill_create",
    "cmd_skill_save_last",
    "cmd_skill_assign",
    "cmd_skill_unassign",
    "cmd_skill_sync",
]