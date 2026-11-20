"""Draft reusable skills from eligible, completed Hive runs (FR-11)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from hobees.config import settings
from hobees.core.llm_factory import get_chat_model
from hobees.db.models import Run, Skill, BeeSkill, Bee, Hive, LLMProvider
from hobees.db.session import session_scope

logger = logging.getLogger(__name__)

_SKILLS_DIR = settings.skills_dir
_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

# Heuristics for triggering skill harvest
MIN_TOOL_CALLS = 4
MIN_HANDOFFS = 2


def should_harvest(run: Run) -> bool:
    """Determine if a run qualifies for skill harvesting."""
    # Check tool calls
    tool_call_count = 0
    handoff_count = 0
    bee_names = set()

    with session_scope() as session:
        run_exists = session.query(Run).filter_by(id=run.id).first()
        if run_exists:
            # Count tool calls from usage_events
            from hobees.db.models import UsageEvent
            ue_rows = session.query(UsageEvent).filter_by(run_id=run.id).all()
            for ue in ue_rows:
                tool_calls = ue.tool_calls or []
                tool_call_count += len(tool_calls)
                bee_names.add(ue.bee_name)

    handoff_count = max(0, len(bee_names) - 1)  # Approximate handoffs

    return tool_call_count >= MIN_TOOL_CALLS or handoff_count >= MIN_HANDOFFS


def harvest_completed_run(run_id: int) -> dict | None:
    """Generate and store a skill draft for an eligible completed Hive run."""
    try:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if not run or run.status != "completed" or not run.hive_id:
                return None
            if run.suggested_skill_draft:
                return run.suggested_skill_draft

            hive = session.get(Hive, run.hive_id)
            if not hive:
                logger.warning("Cannot harvest run %s: Hive %s was not found", run_id, run.hive_id)
                return None
            provider = session.get(LLMProvider, hive.supervisor_provider_id)
            if not provider:
                logger.warning(
                    "Cannot harvest run %s: supervisor provider %s was not found",
                    run_id,
                    hive.supervisor_provider_id,
                )
                return None
            provider_alias = provider.alias
            model_name = hive.supervisor_model_name

        if not should_harvest(run):
            return None

        draft = extract_skill_draft(run, provider_alias, model_name)
        if draft:
            save_skill_draft(run_id, draft)
        return draft
    except Exception:
        logger.exception("Skill harvesting failed for completed run %s", run_id)
        return None


def extract_skill_draft(run: Run, provider_alias: str, model_name: str) -> dict | None:
    """Use an LLM to analyze the run trace and generate a skill draft."""
    # Fetch run details
    with session_scope() as session:
        run_obj = session.get(Run, run.id)
        if not run_obj:
            return None
        goal = run_obj.goal
        hive_id = run_obj.hive_id
        hive_name = None
        if hive_id:
            from hobees.db.models import Hive
            hive = session.get(Hive, hive_id)
            if hive:
                hive_name = hive.name

        # Get usage events for this run
        from hobees.db.models import UsageEvent
        events = (
            session.query(UsageEvent)
            .filter_by(run_id=run.id)
            .order_by(UsageEvent.created_at)
            .all()
        )

    if not events:
        return None

    # Build trace summary
    trace_lines = [f"Goal: {goal}"]
    if hive_name:
        trace_lines.append(f"Hive: {hive_name}")
    trace_lines.append("Execution trace:")
    for ue in events:
        tools = ", ".join(ue.tool_calls) if ue.tool_calls else "none"
        trace_lines.append(
            f"  - {ue.bee_name} ({ue.provider_alias}/{ue.model_name}): "
            f"{ue.input_tokens} in / {ue.output_tokens} out tokens, "
            f"tools=[{tools}]"
        )

    trace = "\n".join(trace_lines)

    # Use the configured supervisor provider and model to generalize.
    try:
        with session_scope() as session:
            provider = session.query(LLMProvider).filter_by(alias=provider_alias).first()
        if not provider:
            logger.warning(
                "Cannot extract skill draft for run %s: provider %r was not found",
                run.id,
                provider_alias,
            )
            return None

        model = get_chat_model(provider, model_name, 0.3)

        prompt = f"""Analyze this execution trace and determine if a reusable skill was discovered.

{trace}

If a reusable procedure exists, output JSON with:
{{
  "name": "kebab-case-skill-name",
  "description": "One-line trigger summary for system prompts",
  "instructions": "Full Markdown workflow (generalized, no temp paths/values)",
  "tags": ["tag1", "tag2"],
  "bee_names": ["bee1", "bee2"]
}}

If NO reusable skill exists, output: {{"none": true}}

Output ONLY the JSON, no extra text."""
        result = model.invoke(prompt)
        content = getattr(result, "content", str(result)).strip()

        # Parse JSON
        try:
            draft = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            match = re.search(r"```(?:json)?\n(\{.*?\})\n```", content, re.DOTALL)
            if not match:
                logger.warning("Skill model returned invalid JSON for run %s", run.id)
                return None
            try:
                draft = json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.warning("Skill model returned invalid JSON for run %s", run.id)
                return None

        if not isinstance(draft, dict):
            logger.warning("Skill model returned a non-object draft for run %s", run.id)
            return None
        if draft.get("none"):
            return None

        name = draft.get("name")
        description = draft.get("description")
        instructions = draft.get("instructions")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            or not isinstance(description, str)
            or not description.strip()
            or not isinstance(instructions, str)
            or not instructions.strip()
        ):
            logger.warning("Skill model returned an incomplete draft for run %s", run.id)
            return None

        tags = draft.get("tags", [])
        bee_names = draft.get("bee_names", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            logger.warning("Skill model returned invalid tags for run %s", run.id)
            return None
        if not isinstance(bee_names, list) or not all(
            isinstance(bee_name, str) for bee_name in bee_names
        ):
            logger.warning("Skill model returned invalid Bee names for run %s", run.id)
            return None
        return draft

    except Exception:
        logger.exception("Skill draft extraction failed for run %s", run.id)
        return None


def save_skill_draft(run_id: int, draft: dict) -> None:
    """Store the skill draft in the run's suggested_skill_draft column."""
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run:
            run.suggested_skill_draft = draft


def persist_skill(draft: dict, source_thread_id: str) -> Skill:
    """Save a skill to the database and write Markdown file."""
    with session_scope() as session:
        skill = Skill(
            name=draft["name"],
            description=draft["description"],
            instructions=draft["instructions"],
            tags=draft.get("tags", []),
            source_thread_id=source_thread_id,
        )
        session.add(skill)
        session.flush()

        # Link to bees if specified
        bee_names = draft.get("bee_names", [])
        if bee_names:
            bees = session.query(Bee).filter(Bee.name.in_(bee_names)).all()
            for bee in bees:
                session.add(BeeSkill(bee_id=bee.id, skill_id=skill.id))

        session.flush()
        skill_id = skill.id

    # Write Markdown file
    md_path = _SKILLS_DIR / f"{draft['name']}.md"
    md_content = f"""# {draft['name']}

**Description:** {draft['description']}

**Tags:** {", ".join(draft.get('tags', []))}

---

{draft['instructions']}
"""
    md_path.write_text(md_content, encoding="utf-8")

    return skill


def sync_skills_from_markdown() -> int:
    """Import skills from ~/.hobees/skills/*.md files."""
    count = 0
    for md_file in _SKILLS_DIR.glob("*.md"):
        name = md_file.stem
        with session_scope() as session:
            existing = session.query(Skill).filter_by(name=name).first()
            if existing:
                continue

        # Parse markdown (simple: first line after # is description)
        content = md_file.read_text(encoding="utf-8")
        lines = content.split("\n")
        description = ""
        instructions = content
        for i, line in enumerate(lines):
            if line.startswith("# "):
                # Title line, next non-empty might be description
                for j in range(i + 1, len(lines)):
                    if lines[j].strip() and not lines[j].startswith("#"):
                        description = lines[j].strip()
                        break
                break

        with session_scope() as session:
            skill = Skill(
                name=name,
                description=description or f"Imported from {md_file.name}",
                instructions=content,
                tags=[],
                source_thread_id=None,
            )
            session.add(skill)
            count += 1

    return count


__all__ = [
    "should_harvest",
    "harvest_completed_run",
    "extract_skill_draft",
    "save_skill_draft",
    "persist_skill",
    "sync_skills_from_markdown",
    "MIN_TOOL_CALLS",
    "MIN_HANDOFFS",
]