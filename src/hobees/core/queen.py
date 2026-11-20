"""Queen Meta-Orchestrator (FR-5, auto mode).

The Queen is a LangChain agent equipped with two DB tools:

* ``inspect_roster()`` — summarize registered Providers, Bees and Hives.
* ``form_and_run_hive(goal, bee_names)`` — assemble a new ``is_dynamic=True``
  Hive in PostgreSQL, run the goal through it, and return the outcome.

v1.1 additions:
- Memory injection
- Thinking level support
- Skill harvesting integration
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool

from hobees.core.hive_builder import hive_app
from hobees.core.llm_factory import get_chat_model
from hobees.core.memory_manager import (
    build_memory_block,
    extract_namespaces,
    extract_run_memories,
)
from hobees.core.skill_harvester import harvest_completed_run
from hobees.db.models import Bee, Hive, HiveMembership, LLMProvider, Run
from hobees.db.session import get_engine, session_scope

QUEEN_PROMPT = """\
You are the Queen Meta-Orchestrator of the hobees swarm. You do not execute
tasks yourself — you inspect the roster of available Worker Bees and Hives,
then either route the goal to an existing Hive or assemble a new dynamic Hive
to accomplish it.

Tools:
- inspect_roster(): see every registered Provider, Bee and Hive.
- form_and_run_hive(goal, bee_names): create a dynamic Hive and run a goal.

When the user gives a goal:
1. Call inspect_roster() to see what exists.
2. If a static Hive fits, say so and form_and_run_hive with its bees.
3. Otherwise call form_and_run_hive() with the goal (and chosen bee names, if
   any obviously fit) so a new dynamic Hive is created and executed.
4. Report the final outcome to the user in plain language.
"""

_WORD = re.compile(r"[a-z0-9]+")


class Queen:
    def __init__(
        self,
        provider: LLMProvider,
        model_name: str,
        db_url: str,
        thread_id: str | None = None,
        thinking_level: str = "medium",
    ) -> None:
        self.provider = provider
        self.model_name = model_name
        self.db_url = db_url
        self.thread_id = thread_id or uuid.uuid4().hex
        self.thinking_level = thinking_level
        self.model = get_chat_model(provider, model_name, 0.0, thinking_level=thinking_level)
        memory_block = build_memory_block(extract_namespaces(global_=True))
        system_prompt = "\n\n".join(
            part for part in (QUEEN_PROMPT, memory_block) if part
        )
        self.agent = create_agent(
            model=self.model,
            tools=[tool(self.inspect_roster), tool(self.form_and_run_hive)],
            system_prompt=system_prompt,
        )

    # -- Queen tools -------------------------------------------------------

    def inspect_roster(self) -> str:
        """Return a text summary of all Providers, Bees and Hives in Postgres."""
        with session_scope() as session:
            providers = session.query(LLMProvider).order_by(LLMProvider.alias).all()
            bees = session.query(Bee).order_by(Bee.name).all()
            hives = session.query(Hive).order_by(Hive.name).all()

        lines = ["🔌 Providers:"]
        for p in providers:
            lines.append(f"  - {p.alias} ({p.provider_type}) default_model={p.default_model}")
        lines.append("🐝 Bees:")
        for b in bees:
            thinking = f" thinking={b.thinking_level}" if b.thinking_level != "off" else ""
            lines.append(
                f"  - {b.name}: {b.role_description} | {b.provider.alias}/{b.model_name}{thinking} | tools={b.tool_names}"
            )
        lines.append("⬡ Hives:")
        for h in hives:
            members = ", ".join(m.bee.name for m in h.memberships) or "none"
            lines.append(
                f"  - {h.name} (dynamic={h.is_dynamic}) supervisor={h.supervisor_provider.alias}/{h.supervisor_model_name} thinking={h.supervisor_thinking_level} | bees={members}"
            )
        return "\n".join(lines)

    def form_and_run_hive(
        self, goal: str, bee_names: str = ""
    ) -> str:
        """Create a dynamic Hive from selected Bees and run ``goal`` through it.

        ``bee_names`` is a comma-separated list of Bee names; when empty the
        Queen auto-selects Bees whose role descriptions best match the goal.
        """
        chosen = self._select_bees(goal, bee_names)
        if not chosen:
            return "Queen: no Worker Bees are registered — register a Bee first (/bee create)."

        hive_id: int | None = None
        run_id: int | None = None
        try:
            with session_scope() as session:
                # Supervisor = the Queen's own provider/model.
                hive = Hive(
                    name=f"dynamic-{uuid.uuid4().hex[:8]}",
                    goal_description=goal,
                    supervisor_provider_id=self.provider.id,
                    supervisor_model_name=self.model_name,
                    supervisor_prompt=None,
                    is_dynamic=True,
                )
                session.add(hive)
                session.flush()
                hive_id = hive.id
                for bee in chosen:
                    session.add(HiveMembership(hive_id=hive.id, bee_id=bee.id))
                run = Run(
                    thread_id=self.thread_id,
                    hive_id=hive.id,
                    mode="auto",
                    goal=goal,
                    status="running",
                )
                session.add(run)
                session.flush()
                run_id = run.id
        except Exception as exc:  # pragma: no cover - depends on live Postgres
            return f"Queen: failed to create dynamic Hive: {exc}"

        providers: dict[int, LLMProvider] = {}
        with session_scope() as session:
            rows = session.query(LLMProvider).all()
            providers = {p.id: p for p in rows}

        try:
            with hive_app(hive, chosen, providers, self.db_url, self.thread_id, run_id, self.thinking_level) as app:
                result = app.invoke(
                    {"messages": [("user", goal)]},
                    config={"configurable": {"thread_id": self.thread_id}},
                )
            output = self._extract_output(result)
            extract_run_memories(
                goal=goal,
                output=output,
                provider=self.provider,
                model_name=self.model_name,
                hive_name=hive.name,
                source_thread_id=self.thread_id,
                allow_hive_facts=False,
            )
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run:
                    run.status = "completed"
                    run.completed_at = datetime.now(timezone.utc)
            harvest_completed_run(run_id)

            return f"Queen: dynamic Hive (id={hive_id}) completed.\n{output}"
        except Exception as exc:  # pragma: no cover - depends on live Postgres/LLM
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run:
                    run.status = "failed"
                    run.completed_at = datetime.now(timezone.utc)
            return f"Queen: dynamic Hive (id={hive_id}) failed: {exc}"

    # -- internals ---------------------------------------------------------

    def _select_bees(self, goal: str, bee_names: str) -> list[Bee]:
        with session_scope() as session:
            bees = session.query(Bee).all()
        if not bees:
            return []
        if bee_names.strip():
            wanted = {n.strip() for n in bee_names.split(",") if n.strip()}
            return [b for b in bees if b.name in wanted]

        goal_words = set(_WORD.findall(goal.lower()))
        scored = []
        for bee in bees:
            text = f"{bee.role_description} {bee.system_prompt} {bee.name}".lower()
            bee_words = set(_WORD.findall(text))
            overlap = len(goal_words & bee_words)
            scored.append((overlap, bee.name, bee))
        scored.sort(key=lambda item: (-item[0], item[1]))
        top = [bee for score, _, bee in scored[:3] if score > 0]
        return top if top else bees[:3]

    @staticmethod
    def _extract_output(result: dict[str, Any]) -> str:
        messages = result.get("messages", []) if isinstance(result, dict) else []
        if not messages:
            return str(result)
        last = messages[-1]
        return getattr(last, "content", str(last))


def build_queen(
    provider: LLMProvider,
    model_name: str,
    db_url: str,
    thread_id: str | None = None,
    thinking_level: str = "medium",
) -> Queen:
    """Factory for a Queen Meta-Orchestrator agent."""
    return Queen(
        provider=provider,
        model_name=model_name,
        db_url=db_url,
        thread_id=thread_id,
        thinking_level=thinking_level,
    )


__all__ = ["Queen", "build_queen", "QUEEN_PROMPT"]