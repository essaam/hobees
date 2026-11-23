"""Database session management: pooled SQLAlchemy engine + PostgresSaver factory.

The engine is created lazily so CLI startup stays fast (Section 3.1). A
``psycopg-pool`` backed connection pool lets the CLI, a second stats terminal,
and the FastAPI API read/write PostgreSQL concurrently without
file-locking bottlenecks.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from hobees.config import settings
from hobees.db.backends import get_database_backend

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return a lazily-created, pooled SQLAlchemy engine."""
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "HOBEES_DATABASE_URL is not set. Configure ~/.hobees/.env or a local .env, "
                "then run `hobees init`."
            )
        backend = get_database_backend(settings.database_url)
        engine_options: dict[str, Any] = {"pool_pre_ping": True, "echo": False}
        if backend == "postgresql":
            engine_options.update(pool_size=5, max_overflow=10)
        _engine = create_engine(settings.database_url, **engine_options)
        inspector = inspect(_engine)
        if "runs" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("runs")}
            additions = {}
            if "artifacts_dir" not in columns:
                additions["artifacts_dir"] = "VARCHAR(1024)"
            if "container_name" not in columns:
                additions["container_name"] = "VARCHAR(128)"
            if additions:
                with _engine.begin() as connection:
                    for column_name, column_type in additions.items():
                        connection.execute(
                            text(f"ALTER TABLE runs ADD COLUMN {column_name} {column_type}")
                        )
        if "bees" in inspect(_engine).get_table_names():
            columns = {column["name"] for column in inspect(_engine).get_columns("bees")}
            if "require_approval" not in columns:
                with _engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE bees ADD COLUMN require_approval JSON DEFAULT '[]'")
                    )
        if "usage_events" in inspect(_engine).get_table_names():
            usage_columns = {
                column["name"] for column in inspect(_engine).get_columns("usage_events")
            }
            if usage_columns:
                with _engine.begin() as connection:
                    if "container_name" not in usage_columns:
                        connection.execute(
                            text("ALTER TABLE usage_events ADD COLUMN container_name VARCHAR(128)")
                        )
                    if "checkpoint_id" not in usage_columns:
                        connection.execute(
                            text("ALTER TABLE usage_events ADD COLUMN checkpoint_id VARCHAR(128)")
                        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return a configured SQLAlchemy sessionmaker bound to the pooled engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional scope around a series of ORM operations."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Dispose the engine pool (useful in tests and shutdown hooks)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _SessionLocal = None


__all__ = [
    "get_engine",
    "get_session_factory",
    "session_scope",
    "dispose_engine",
]
