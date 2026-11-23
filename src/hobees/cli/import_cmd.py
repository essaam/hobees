"""Configuration import command for hobees.

Allows importing providers, bees, hives, memories, and skills from a YAML/JSON file.
API keys are read from environment variables for security.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

from hobees.cli.icons import SUCCESS, ERROR, WARN, APP, BEE, HIVE, MEMORY, SKILL

console = Console()


def _load_config_file(path: Path) -> dict:
    """Load configuration from YAML or JSON file."""
    if not path.exists():
        console.print(f"{ERROR} Config file not found: {path}")
        raise typer.Exit(code=1)
    
    content = path.read_text(encoding="utf-8")
    
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
            return yaml.safe_load(content) or {}
        except ImportError:
            console.print(f"{ERROR} PyYAML not installed. Run: pip install pyyaml")
            raise typer.Exit(code=1)
        except yaml.YAMLError as e:
            console.print(f"{ERROR} Invalid YAML: {e}")
            raise typer.Exit(code=1)
    elif path.suffix.lower() == ".json":
        import json
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            console.print(f"{ERROR} Invalid JSON: {e}")
            raise typer.Exit(code=1)
    else:
        console.print(f"{ERROR} Unsupported file format: {path.suffix}. Use .yaml, .yml, or .json")
        raise typer.Exit(code=1)


def _resolve_env_vars(obj: Any) -> Any:
    """Recursively resolve ${ENV_VAR} or $ENV_VAR patterns in strings."""
    if isinstance(obj, str):
        # Handle ${VAR} or $VAR patterns
        import re
        def replace_var(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        
        # Replace ${VAR} patterns
        result = re.sub(r'\$\{([^}]+)\}', replace_var, obj)
        # Replace $VAR patterns (but not ${VAR})
        result = re.sub(r'(?<!\$)\$([A-Z_][A-Z0-9_]*)', replace_var, result)
        return result
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def _import_providers(config: dict, dry_run: bool = False) -> Dict[str, int]:
    """Import providers from config. Returns mapping of alias -> provider_id."""
    from hobees.db.session import session_scope
    from hobees.db.models import LLMProvider
    from hobees.cli.provider_cmd import VALID_TYPES
    
    providers_config = config.get("providers", [])
    if not providers_config:
        return {}
    
    alias_to_id = {}
    
    with session_scope() as session:
        for p in providers_config:
            alias = p.get("alias")
            if not alias:
                console.print(f"{WARN} Skipping provider without alias")
                continue
            
            provider_type = p.get("provider_type")
            if provider_type not in VALID_TYPES:
                console.print(f"{WARN} Provider {alias!r}: invalid provider_type {provider_type!r}, skipping")
                continue
            
            # Check if already exists
            existing = session.query(LLMProvider).filter_by(alias=alias).first()
            base_url = p.get("base_url")
            if base_url:
                base_url = _resolve_env_vars(base_url)
            api_key_env = p.get("api_key_env", "NONE")
            if api_key_env != "NONE" and not os.environ.get(api_key_env):
                console.print(f"  {WARN} Provider {alias!r}: env var {api_key_env!r} not set")

            if existing:
                console.print(f"  {WARN} Provider {alias!r} already exists, updating")
                if dry_run:
                    alias_to_id[alias] = existing.id
                    continue
                existing.provider_type = provider_type
                existing.base_url = base_url
                existing.api_key_env = api_key_env
                existing.default_model = p.get("default_model")
                existing.assistant_model = p.get("assistant_model")
                existing.input_cost_per_1m = p.get("input_cost_per_1m", 0.0)
                existing.output_cost_per_1m = p.get("output_cost_per_1m", 0.0)
                existing.context_window_tokens = p.get("context_window_tokens", 128000)
                alias_to_id[alias] = existing.id
                continue
            
            if dry_run:
                console.print(f"  {APP} Would create provider: {alias} ({provider_type})")
                continue
            
            row = LLMProvider(
                alias=alias,
                provider_type=provider_type,
                base_url=base_url,
                api_key_env=api_key_env,
                default_model=p.get("default_model"),
                assistant_model=p.get("assistant_model"),
                input_cost_per_1m=p.get("input_cost_per_1m", 0.0),
                output_cost_per_1m=p.get("output_cost_per_1m", 0.0),
                context_window_tokens=p.get("context_window_tokens", 128000),
            )
            session.add(row)
            session.flush()
            alias_to_id[alias] = row.id
            console.print(f"  {SUCCESS} Created provider: {alias} ({provider_type})")
    
    return alias_to_id


def _import_bees(config: dict, provider_alias_to_id: Dict[str, int], dry_run: bool = False) -> Dict[str, int]:
    """Import bees from config. Returns mapping of bee_name -> bee_id."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee
    
    bees_config = config.get("bees", [])
    if not bees_config:
        return {}
    
    bee_name_to_id = {}
    
    with session_scope() as session:
        for b in bees_config:
            name = b.get("name")
            if not name:
                console.print(f"{WARN} Skipping bee without name")
                continue
            
            provider_alias = b.get("provider")
            if not provider_alias:
                console.print(f"{WARN} Bee {name!r}: no provider specified, skipping")
                continue
            
            provider_id = provider_alias_to_id.get(provider_alias)
            if not provider_id:
                console.print(f"{WARN} Bee {name!r}: provider {provider_alias!r} not found, skipping")
                continue
            
            # Check if already exists
            tool_names = b.get("tools", [])
            if isinstance(tool_names, str):
                tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]
            require_approval = b.get("require_approval", [])
            if isinstance(require_approval, str):
                require_approval = [t.strip() for t in require_approval.split(",") if t.strip()]
            unknown = [name for name in require_approval if name not in tool_names]
            if unknown:
                console.print(
                    f"{WARN} Bee {name!r}: require_approval contains tools outside tools: "
                    f"{', '.join(unknown)}"
                )

            existing = session.query(Bee).filter_by(name=name).first()
            if existing:
                if dry_run:
                    bee_name_to_id[name] = existing.id
                    console.print(f"  {BEE} Would update bee: {name} (provider={provider_alias})")
                    continue
                existing.role_description = b.get("role_description", "")
                existing.system_prompt = b.get("system_prompt", "")
                existing.provider_id = provider_id
                existing.model_name = b.get("model") or b.get("default_model", "")
                existing.temperature = b.get("temperature", 0.0)
                existing.thinking_level = b.get("thinking_level", "off")
                existing.tool_names = tool_names
                existing.require_approval = require_approval
                bee_name_to_id[name] = existing.id
                console.print(f"  {SUCCESS} Updated bee: {name}")
                continue
            
            if dry_run:
                console.print(f"  {BEE} Would create bee: {name} (provider={provider_alias})")
                continue
            
            bee = Bee(
                name=name,
                role_description=b.get("role_description", ""),
                system_prompt=b.get("system_prompt", ""),
                provider_id=provider_id,
                model_name=b.get("model") or b.get("default_model", ""),
                temperature=b.get("temperature", 0.0),
                thinking_level=b.get("thinking_level", "off"),
                tool_names=tool_names,
                require_approval=require_approval,
            )
            session.add(bee)
            session.flush()
            bee_name_to_id[name] = bee.id
            console.print(f"  {SUCCESS} Created bee: {name} (provider={provider_alias}, model={bee.model_name})")
    
    return bee_name_to_id


def _import_hives(config: dict, provider_alias_to_id: Dict[str, int], 
                  bee_name_to_id: Dict[str, int], dry_run: bool = False) -> Dict[str, int]:
    """Import hives from config. Returns mapping of hive_name -> hive_id."""
    from hobees.db.session import session_scope
    from hobees.db.models import Hive, HiveMembership
    from pathlib import Path
    
    hives_config = config.get("hives", [])
    if not hives_config:
        return {}
    
    hive_name_to_id = {}
    
    with session_scope() as session:
        for h in hives_config:
            name = h.get("name")
            if not name:
                console.print(f"{WARN} Skipping hive without name")
                continue
            
            supervisor_provider_alias = h.get("supervisor_provider")
            if not supervisor_provider_alias:
                console.print(f"{WARN} Hive {name!r}: no supervisor_provider specified, skipping")
                continue
            
            supervisor_provider_id = provider_alias_to_id.get(supervisor_provider_alias)
            if not supervisor_provider_id:
                console.print(f"{WARN} Hive {name!r}: supervisor provider {supervisor_provider_alias!r} not found, skipping")
                continue
            
            existing = session.query(Hive).filter_by(name=name).first()
            
            project_path = h.get("project_path")
            if project_path:
                project_path = _resolve_env_vars(project_path)
                path = Path(project_path).expanduser().resolve()
                path.mkdir(parents=True, exist_ok=True)
            
            if dry_run:
                action = "update" if existing else "create"
                console.print(f"  {HIVE} Would {action} hive: {name} (supervisor={supervisor_provider_alias})")
                continue
            
            if existing:
                hive = existing
                hive.goal_description = h.get("goal_description")
                hive.supervisor_provider_id = supervisor_provider_id
                hive.supervisor_model_name = h.get("supervisor_model", "gpt-4o-mini")
                hive.supervisor_prompt = h.get("supervisor_prompt")
                hive.supervisor_thinking_level = h.get("supervisor_thinking_level", "medium")
                hive.is_dynamic = h.get("is_dynamic", False)
                hive.project_path = project_path
                console.print(f"  {SUCCESS} Updated hive: {name}")
            else:
                hive = Hive(
                    name=name,
                    goal_description=h.get("goal_description"),
                    supervisor_provider_id=supervisor_provider_id,
                    supervisor_model_name=h.get("supervisor_model", "gpt-4o-mini"),
                    supervisor_prompt=h.get("supervisor_prompt"),
                    supervisor_thinking_level=h.get("supervisor_thinking_level", "medium"),
                    is_dynamic=h.get("is_dynamic", False),
                    project_path=project_path,
                )
                session.add(hive)
                session.flush()
                console.print(f"  {SUCCESS} Created hive: {name} (supervisor={supervisor_provider_alias})")
            hive_name_to_id[name] = hive.id
            
            # Add bees to hive
            bee_names = h.get("bees", [])
            configured_bee_ids = set()
            all_bees_resolved = True
            for bee_name in bee_names:
                bee_id = bee_name_to_id.get(bee_name)
                if bee_id:
                    configured_bee_ids.add(bee_id)
                    membership = session.get(HiveMembership, (hive.id, bee_id))
                    if membership is None:
                        session.add(HiveMembership(hive_id=hive.id, bee_id=bee_id))
                        console.print(f"    {SUCCESS} Added bee {bee_name!r} to hive {name!r}")
                else:
                    all_bees_resolved = False
                    console.print(f"    {WARN} Bee {bee_name!r} not found, skipping")
            if "bees" in h and all_bees_resolved:
                session.query(HiveMembership).filter(
                    HiveMembership.hive_id == hive.id,
                    ~HiveMembership.bee_id.in_(configured_bee_ids),
                ).delete(synchronize_session=False)
    
    return hive_name_to_id


def _import_memory(config: dict, dry_run: bool = False) -> int:
    """Import memory entries from config."""
    from hobees.db.session import session_scope
    from hobees.db.models import Memory
    
    memory_config = config.get("memory", [])
    if not memory_config:
        return 0
    
    count = 0
    
    with session_scope() as session:
        for m in memory_config:
            namespace = m.get("namespace", "global")
            key = m.get("key")
            content = m.get("content")
            
            if not key or not content:
                console.print(f"{WARN} Skipping memory entry without key or content")
                continue
            
            if dry_run:
                console.print(f"  {MEMORY} Would create memory: {namespace}/{key}")
                continue
            
            existing = session.query(Memory).filter_by(namespace=namespace, key=key).first()
            if existing:
                existing.content = content
                existing.source_thread_id = m.get("source_thread_id")
            else:
                session.add(Memory(
                    namespace=namespace,
                    key=key,
                    content=content,
                    source_thread_id=m.get("source_thread_id"),
                ))
            count += 1
            console.print(f"  {SUCCESS} Created memory: {namespace}/{key}")
    
    return count


def _import_skills(config: dict, bee_name_to_id: Dict[str, int], dry_run: bool = False) -> int:
    """Import skills from config."""
    from hobees.db.session import session_scope
    from hobees.db.models import Skill, BeeSkill, Bee
    
    skills_config = config.get("skills", [])
    if not skills_config:
        return 0
    
    count = 0
    
    with session_scope() as session:
        for s in skills_config:
            name = s.get("name")
            if not name:
                console.print(f"{WARN} Skipping skill without name")
                continue
            
            if dry_run:
                console.print(f"  {SKILL} Would create skill: {name}")
                continue
            
            # Check if skill exists
            skill = session.query(Skill).filter_by(name=name).first()
            if not skill:
                skill = Skill(
                    name=name,
                    description=s.get("description", ""),
                    instructions=s.get("instructions", ""),
                    tags=s.get("tags", []),
                )
                session.add(skill)
                session.flush()
                console.print(f"  {SUCCESS} Created skill: {name}")
            else:
                # Update existing
                skill.description = s.get("description", skill.description)
                skill.instructions = s.get("instructions", skill.instructions)
                skill.tags = s.get("tags", skill.tags)
                console.print(f"  {SUCCESS} Updated skill: {name}")
            
            # Assign to bees if specified
            bee_names = s.get("bees", [])
            configured_bee_ids = set()
            all_bees_resolved = True
            for bee_name in bee_names:
                bee_id = bee_name_to_id.get(bee_name)
                if bee_id:
                    configured_bee_ids.add(bee_id)
                    # Check if already assigned
                    existing = session.query(BeeSkill).filter_by(bee_id=bee_id, skill_id=skill.id).first()
                    if not existing:
                        session.add(BeeSkill(bee_id=bee_id, skill_id=skill.id))
                        console.print(f"    {SUCCESS} Assigned skill {name!r} to bee {bee_name!r}")
                else:
                    all_bees_resolved = False
            if "bees" in s and all_bees_resolved:
                session.query(BeeSkill).filter(
                    BeeSkill.skill_id == skill.id,
                    ~BeeSkill.bee_id.in_(configured_bee_ids),
                ).delete(synchronize_session=False)
            
            count += 1
    
    return count


def _import_assistant(config: dict, provider_alias_to_id: Dict[str, int], dry_run: bool = False) -> bool:
    """Import assistant configuration from config."""
    from hobees.db.session import session_scope
    from hobees.db.models import Bee, LLMProvider
    
    assistant_config = config.get("assistant")
    if not assistant_config:
        console.print(f"  {WARN} No assistant configuration found")
        return False
    
    provider_alias = assistant_config.get("provider")
    if not provider_alias:
        console.print(f"  {ERROR} Assistant config missing provider")
        return False
    
    provider_id = provider_alias_to_id.get(provider_alias)
    if not provider_id:
        console.print(f"  {ERROR} Provider {provider_alias!r} not found")
        return False
    
    if dry_run:
        console.print(f"  {APP} Would create/update assistant bee with provider={provider_alias}, model={assistant_config.get('model')}")
        return True
    
    tool_names = assistant_config.get("tools", [])
    if isinstance(tool_names, str):
        tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]
    
    with session_scope() as session:
        # Check if assistant already exists
        assistant = session.query(Bee).filter_by(name="assistant").first()
        
        if assistant:
            # Update existing assistant
            assistant.provider_id = provider_id
            assistant.model_name = assistant_config.get("model", assistant_config.get("default_model", "gpt-4o-mini"))
            assistant.temperature = assistant_config.get("temperature", 0.7)
            assistant.thinking_level = assistant_config.get("thinking_level", "off")
            assistant.tool_names = tool_names
            console.print(f"  {SUCCESS} Updated assistant bee with provider={provider_alias}, model={assistant.model_name}")
        else:
            # Create new assistant
            assistant = Bee(
                name="assistant",
                role_description="General-purpose assistant that can help with setup, answer questions, and execute tasks using available tools.",
                system_prompt="You are a helpful AI assistant. You can use tools to read/write files, run calculations, and help the user set up providers, bees, and hives. Be friendly and proactive in helping them get started.",
                provider_id=provider_id,
                model_name=assistant_config.get("model", assistant_config.get("default_model", "gpt-4o-mini")),
                temperature=assistant_config.get("temperature", 0.7),
                thinking_level=assistant_config.get("thinking_level", "off"),
                tool_names=tool_names,
            )
            session.add(assistant)
            session.flush()
            console.print(f"  {SUCCESS} Created assistant bee with provider={provider_alias}, model={assistant.model_name}")
    
    return True


def _show_summary(config: dict) -> None:
    """Show a summary of what will be imported."""
    table = Table(title="Import Summary")
    table.add_column("Resource", style="cyan")
    table.add_column("Count", justify="right")
    
    for resource in ["providers", "bees", "hives", "memory", "skills", "assistant"]:
        count = 1 if config.get(resource) else 0
        if count > 0:
            table.add_row(resource.capitalize(), str(count))
    
    console.print(table)


def import_config(
    config_file: Annotated[Path, typer.Argument(help="Path to config file (YAML or JSON)")],
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Show what would be imported without making changes")] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation prompt")] = False,
) -> None:
    """Import hobees configuration from a YAML/JSON file.
    
    The config file can define:
    - providers: LLM providers (API keys from env vars)
    - bees: Worker bees referencing providers by alias
    - hives: Hives referencing bees by name and supervisor provider by alias
    - memory: Cross-session memory entries
    - skills: Reusable skills with optional bee assignments
    
    Example: hobees import config.yaml
    """
    config = _load_config_file(config_file)
    config = _resolve_env_vars(config)
    
    if not config:
        console.print(f"{WARN} Config file is empty")
        return
    
    _show_summary(config)
    
    if dry_run:
        console.print(f"\n{APP} [bold]DRY RUN[/bold] - No changes will be made")
        return
    
    if not force:
        if not Confirm.ask("\nProceed with import?"):
            console.print("Import cancelled.")
            return
    
    console.print()
    
    # Import in order: providers -> bees -> hives -> memory -> skills
    console.print(f"[bold]Importing providers...[/bold]")
    provider_alias_to_id = _import_providers(config, dry_run)
    
    console.print(f"\n[bold]Importing bees...[/bold]")
    bee_name_to_id = _import_bees(config, provider_alias_to_id, dry_run)
    
    console.print(f"\n[bold]Importing hives...[/bold]")
    _import_hives(config, provider_alias_to_id, bee_name_to_id, dry_run)
    
    console.print(f"\n[bold]Importing memory...[/bold]")
    _import_memory(config, dry_run)
    
    console.print(f"\n[bold]Importing skills...[/bold]")
    _import_skills(config, bee_name_to_id, dry_run)
    
    console.print(f"\n[bold]Importing assistant...[/bold]")
    _import_assistant(config, provider_alias_to_id, dry_run)
    
    if not dry_run:
        console.print(f"\n{SUCCESS} Import complete!")
    else:
        console.print(f"\n{APP} Dry run complete. Run without --dry-run to apply.")


__all__ = ["import_config"]