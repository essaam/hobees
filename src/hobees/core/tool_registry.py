"""Built-in local Python tools and the :data:`TOOL_REGISTRY` lookup table.

Tools are plain functions decorated with ``langchain_core.tools.tool`` so they
can be bound directly to LangChain chat models and handed to LangGraph agents.
Bee definitions reference tools by key name via ``bee.tool_names`` (JSONB).

v1.1 additions:
- Tool output truncation & scratchpad offloading
- load_skill tool for progressive skill loading
- save_memory / recall_memory tools for long-term memory
"""

from __future__ import annotations

import ast
from contextvars import ContextVar
import math
import operator as op
from pathlib import Path
from typing import Annotated, Callable

from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool

from hobees.config import settings
from hobees.core.context_manager import truncate_tool_output
from hobees.core.memory_manager import save_memory, recall_memory

# Supported binary/unary operators for the safe expression calculator.
_BIN_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
}
_UN_OPS = {ast.UAdd: op.pos, ast.USub: op.neg}


def _safe_eval(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN_OPS:
        return _UN_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


# Invocation context follows async tasks and context-aware worker threads.
_thread_id_var: ContextVar[str] = ContextVar("hobees_thread_id", default="unknown")
_call_id_var: ContextVar[str] = ContextVar("hobees_call_id", default="unknown")
_project_root_var: ContextVar[str | None] = ContextVar(
    "hobees_project_root", default=None
)


def _get_thread_id() -> str:
    return _thread_id_var.get()


def _get_call_id() -> str:
    return _call_id_var.get()


def _get_project_root() -> str | None:
    return _project_root_var.get()


def _resolve_tool_path(path: str, *, write: bool = False) -> Path:
    project_root = _get_project_root()
    if not project_root:
        try:
            return Path(path).resolve()
        except OSError as exc:
            raise ValueError(f"{path!r} cannot be resolved on this system: {exc}") from exc

    root = Path(project_root).resolve()
    allowed_root = (root / "output").resolve() if write else root
    requested_path = Path(path)
    if write and not requested_path.is_absolute() and requested_path.parts[:1] == ("output",):
        requested_path = Path(*requested_path.parts[1:])
    try:
        resolved = (
            requested_path.resolve()
            if requested_path.is_absolute()
            else (allowed_root / requested_path).resolve()
        )
    except OSError as exc:
        # Windows rejects path segments containing `:` (the default thread key is
        # namespaced), so a raw key passed back to a tool must fail with a clear
        # message instead of an unhandled OSError.
        raise ValueError(f"{path!r} cannot be resolved on this system: {exc}") from exc
    if not resolved.is_relative_to(allowed_root):
        scope = "output directory" if write else "project root"
        raise ValueError(f"{path!r} is outside the configured {scope}")
    return resolved


def set_thread_context(thread_id: str, call_id: str | None = None, project_root: str | None = None) -> None:
    """Set the current thread context for tool output truncation and project root."""
    _thread_id_var.set(thread_id)
    if call_id is not None:
        _call_id_var.set(call_id)
    _project_root_var.set(project_root)


def _wrap_tool_with_truncation(tool_func: Callable) -> Callable:
    """Wrap a tool function to truncate its output if it exceeds the limit."""
    import functools

    @functools.wraps(tool_func)
    def wrapper(*args, **kwargs):
        result = tool_func(*args, **kwargs)
        # Only truncate string outputs
        if isinstance(result, str):
            project_root = _get_project_root()
            scratchpad_root = (
                Path(project_root) / "scratchpad" if project_root else None
            )
            return truncate_tool_output(
                result,
                _get_call_id(),
                _get_thread_id(),
                scratchpad_root=scratchpad_root,
            )
        return result

    return wrapper


@tool
def read_file(path: str) -> str:
    """Read and return the contents of a file at ``path`` (relative to project root or cwd)."""
    try:
        p = _resolve_tool_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not p.is_file():
        return f"ERROR: {path} is not a readable file"
    try:
        return p.read_text(encoding="utf-8")
    except OSError as exc:
        return f"ERROR: {exc}"


@tool
def write_file(path: str, content: str) -> str:
    """Write ``content`` under the project's output directory (or cwd when unscoped)."""
    try:
        p = _resolve_tool_path(path, write=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"WROTE {p} ({len(content)} bytes)"
    except (OSError, ValueError) as exc:
        return f"ERROR: {exc}"


@tool
def list_directory(path: str = ".") -> str:
    """List entries in ``path`` (default project root or cwd), one per line with size info."""
    try:
        p = _resolve_tool_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not p.is_dir():
        return f"ERROR: {path} is not a directory"
    lines = []
    for entry in sorted(p.iterdir()):
        try:
            marker = "/" if entry.is_dir() else ""
            stat = entry.stat()
            lines.append(f"{entry.name}{marker}  ({stat.st_size} bytes)")
        except OSError:
            lines.append(f"{entry.name}  (stat failed)")
    return "\n".join(lines) or "(empty directory)"


@tool
def run_python_calc(expression: str) -> str:
    """Safely evaluate a numeric arithmetic expression (+ - * / % ** // - +)."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree)
        return f"{expression} = {result}"
    except Exception as exc:
        return f"ERROR: cannot evaluate {expression!r}: {exc}"


# v1.1: Progressive skill loading
@tool
def load_skill(skill_name: str) -> str:
    """Load the full instructions for a skill by name.

    Use this when you need to follow a specific procedure.
    The skill will be fetched from the skill library and its usage count incremented.
    """
    from hobees.db.session import session_scope
    from hobees.db.models import Skill

    with session_scope() as session:
        skill = session.query(Skill).filter_by(name=skill_name).first()
        if not skill:
            return f"ERROR: Skill '{skill_name}' not found"
        skill.usage_count += 1
        return skill.instructions


# Memory tools are imported from memory_manager
# save_memory and recall_memory are already decorated with @tool

# Build registry with truncation wrappers
_BASE_TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "run_python_calc": run_python_calc,
    "load_skill": load_skill,
    "save_memory": save_memory,
    "recall_memory": recall_memory,
}

# Apply truncation wrapper to all tools
TOOL_REGISTRY: dict[str, BaseTool] = {}
for name, tool_obj in _BASE_TOOLS.items():
    # The @tool decorator returns a StructuredTool, we need to wrap its func
    if hasattr(tool_obj, "func"):
        original_func = tool_obj.func
        wrapped_func = _wrap_tool_with_truncation(original_func)
        # Create a new tool with the wrapped function
        from langchain_core.tools import StructuredTool
        TOOL_REGISTRY[name] = StructuredTool.from_function(
            func=wrapped_func,
            name=tool_obj.name,
            description=tool_obj.description,
            args_schema=tool_obj.args_schema,
        )
    else:
        TOOL_REGISTRY[name] = tool_obj


def unknown_tool_names(names: list[str] | None) -> list[str]:
    """Tool names that are not registered.

    A Bee can only be gated on a tool it can actually call: `get_tools()` skips
    unknown names, so a `require_approval` entry that is not in
    :data:`TOOL_REGISTRY` can never fire (the README examples used `run_shell`,
    which is not a built-in tool).
    """
    return [name for name in (names or []) if name not in TOOL_REGISTRY]


def get_tools(tool_names: list[str] | None) -> list[BaseTool]:
    """Return the registered :class:`BaseTool` instances for the given names.

    Unknown names are skipped so a Bee with a mistyped tool still loads.
    """
    if not tool_names:
        return []
    return [TOOL_REGISTRY[name] for name in tool_names if name in TOOL_REGISTRY]


def get_skill_metadata() -> list[dict]:
    """Get metadata for all skills (for injection into prompts)."""
    from hobees.db.session import session_scope
    from hobees.db.models import Skill

    with session_scope() as session:
        skills = session.query(Skill).order_by(Skill.name).all()
        return [
            {"name": s.name, "description": s.description}
            for s in skills
        ]


__all__ = [
    "read_file",
    "write_file",
    "list_directory",
    "run_python_calc",
    "load_skill",
    "save_memory",
    "recall_memory",
    "TOOL_REGISTRY",
    "get_tools",
    "unknown_tool_names",
    "get_skill_metadata",
    "set_thread_context",
]