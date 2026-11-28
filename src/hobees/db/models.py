"""SQLAlchemy ORM models mirroring the PostgreSQL schema in Section 5 of the SRS
and the v1.1 addendum (context, memory, skills, model discovery, thinking levels)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, List

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Shared column helpers
IntPK = Annotated[int, mapped_column(Integer, primary_key=True)]
Str64 = Annotated[str, mapped_column(String(64))]
Str32 = Annotated[str, mapped_column(String(32))]
Str128 = Annotated[str, mapped_column(String(128))]
Str255 = Annotated[str, mapped_column(String(255))]
TextCol = Annotated[str, mapped_column(Text)]
TimestampTZ = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now())
]
OptionalTimestampTZ = Annotated[
    datetime | None,
    mapped_column(DateTime(timezone=True), default=None),
]
NumericCost = Annotated[
    float, mapped_column(Numeric(12, 6), default=0.0)
]


class Base(DeclarativeBase):
    pass


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[IntPK]
    alias: Mapped[Str64] = mapped_column(String(64), unique=True, nullable=False)
    provider_type: Mapped[Str32] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(255), default=None)
    api_key_env: Mapped[str] = mapped_column(String(64), nullable=False)
    default_model: Mapped[str | None] = mapped_column(String(128), default=None)
    input_cost_per_1m: Mapped[float] = mapped_column(Numeric(10, 4), default=0.0)
    output_cost_per_1m: Mapped[float] = mapped_column(Numeric(10, 4), default=0.0)
    # v1.1 additions
    context_window_tokens: Mapped[int] = mapped_column(Integer, default=128000)
    available_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    models_refreshed_at: Mapped[OptionalTimestampTZ]
    created_at: Mapped[TimestampTZ]
    # v1.2: assistant-specific model
    assistant_model: Mapped[str | None] = mapped_column(String(128), default=None)

    bees: Mapped[List["Bee"]] = relationship(
        "Bee", back_populates="provider", lazy="selectin"
    )
    supervised_hives: Mapped[List["Hive"]] = relationship(
        "Hive",
        foreign_keys="[Hive.supervisor_provider_id]",
        back_populates="supervisor_provider",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LLMProvider alias={self.alias!r} type={self.provider_type!r}>"


class Bee(Base):
    __tablename__ = "bees"

    id: Mapped[IntPK]
    name: Mapped[Str64] = mapped_column(String(64), unique=True, nullable=False)
    role_description: Mapped[TextCol] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[TextCol] = mapped_column(Text, nullable=False)
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("llm_providers.id", ondelete="RESTRICT"), nullable=False
    )
    model_name: Mapped[Str128] = mapped_column(String(128), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    # v1.1: thinking level
    thinking_level: Mapped[str] = mapped_column(String(16), default="off")  # off|low|medium|high
    tool_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    require_approval: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[TimestampTZ]

    provider: Mapped["LLMProvider"] = relationship(
        "LLMProvider", back_populates="bees", lazy="selectin"
    )
    memberships: Mapped[List["HiveMembership"]] = relationship(
        "HiveMembership", back_populates="bee", cascade="all, delete-orphan"
    )
    skills: Mapped[List["Skill"]] = relationship(
        "Skill", secondary="bee_skills", back_populates="bees", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Bee name={self.name!r} model={self.model_name!r}>"


class Hive(Base):
    __tablename__ = "hives"

    id: Mapped[IntPK]
    name: Mapped[Str64] = mapped_column(String(64), unique=True, nullable=False)
    goal_description: Mapped[str | None] = mapped_column(Text, default=None)
    supervisor_provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("llm_providers.id", ondelete="RESTRICT"), nullable=False
    )
    supervisor_model_name: Mapped[Str128] = mapped_column(String(128), nullable=False)
    supervisor_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    # v1.1: supervisor thinking level
    supervisor_thinking_level: Mapped[str] = mapped_column(String(16), default="medium")
    is_dynamic: Mapped[bool] = mapped_column(Boolean, default=False)
    # Project working directory (subdirectory under project root)
    project_path: Mapped[str | None] = mapped_column(String(512), default=None)
    created_at: Mapped[TimestampTZ]

    supervisor_provider: Mapped["LLMProvider"] = relationship(
        "LLMProvider",
        foreign_keys=[supervisor_provider_id],
        back_populates="supervised_hives",
        lazy="selectin",
    )
    memberships: Mapped[List["HiveMembership"]] = relationship(
        "HiveMembership", back_populates="hive", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Hive name={self.name!r} dynamic={self.is_dynamic}>"


class HiveMembership(Base):
    __tablename__ = "hive_memberships"

    hive_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hives.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bees.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_override: Mapped[str | None] = mapped_column(Text, default=None)

    hive: Mapped["Hive"] = relationship("Hive", back_populates="memberships")
    bee: Mapped["Bee"] = relationship("Bee", back_populates="memberships")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<HiveMembership hive_id={self.hive_id} bee_id={self.bee_id}>"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[IntPK]
    thread_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    container_name: Mapped[str | None] = mapped_column(String(128), default=None)
    hive_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hives.id", ondelete="SET NULL"), default=None
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # 'hive' | 'auto'
    goal: Mapped[TextCol] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="running"
    )  # 'running' | 'completed' | 'failed'
    artifacts_dir: Mapped[str | None] = mapped_column(String(1024), default=None)
    started_at: Mapped[TimestampTZ]
    completed_at: Mapped[OptionalTimestampTZ]
    # v1.1 additions
    compacted_count: Mapped[int] = mapped_column(Integer, default=0)
    suggested_skill_draft: Mapped[dict | None] = mapped_column(JSON, default=None)

    usage_events: Mapped[List["UsageEvent"]] = relationship(
        "UsageEvent", back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Run thread_id={self.thread_id!r} status={self.status!r}>"


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("runs.id", ondelete="CASCADE"), default=None
    )
    thread_id: Mapped[str] = mapped_column(String(512), nullable=False)
    container_name: Mapped[str | None] = mapped_column(String(128), default=None)
    checkpoint_id: Mapped[str | None] = mapped_column(String(128), default=None)
    bee_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_alias: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[TimestampTZ]

    run: Mapped["Run | None"] = relationship("Run", back_populates="usage_events")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UsageEvent bee={self.bee_name!r} cost=${self.estimated_cost_usd}>"


class ApprovalEvent(Base):
    __tablename__ = "approval_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_name: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(512), nullable=False)
    checkpoint_id: Mapped[str | None] = mapped_column(String(128), default=None)
    hive_name: Mapped[str | None] = mapped_column(String(64), default=None)
    bee_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    original_args_json: Mapped[str | None] = mapped_column(Text, default=None)
    final_args_json: Mapped[str | None] = mapped_column(Text, default=None)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    requested_at: Mapped[TimestampTZ]
    resolved_at: Mapped[OptionalTimestampTZ]

    __table_args__ = (
        Index("ix_approval_events_container_name", "container_name"),
        Index("ix_approval_events_thread_id", "thread_id"),
        Index("ix_approval_events_checkpoint_id", "checkpoint_id"),
    )


# v1.1: Cross-session scoped memory store
class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[IntPK]
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)  # 'global' | 'hive:<name>' | 'bee:<name>'
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_thread_id: Mapped[str | None] = mapped_column(String(512), default=None)
    updated_at: Mapped[TimestampTZ]

    __table_args__ = (
        Index("ix_memories_namespace", "namespace"),
        Index("ux_memories_namespace_key", "namespace", "key", unique=True),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Memory namespace={self.namespace!r} key={self.key!r}>"


# v1.1: Reusable procedural skills library
class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[IntPK]
    name: Mapped[Str64] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_thread_id: Mapped[str | None] = mapped_column(String(512), default=None)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[TimestampTZ]
    updated_at: Mapped[TimestampTZ]

    bees: Mapped[List["Bee"]] = relationship(
        "Bee", secondary="bee_skills", back_populates="skills", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Skill name={self.name!r}>"


# v1.1: Many-to-many assignment of skills to Bees
class BeeSkill(Base):
    __tablename__ = "bee_skills"

    bee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bees.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BeeSkill bee_id={self.bee_id} skill_id={self.skill_id}>"


__all__ = [
    "Base",
    "LLMProvider",
    "Bee",
    "Hive",
    "HiveMembership",
    "Run",
    "UsageEvent",
    "Memory",
    "Skill",
    "BeeSkill",
]