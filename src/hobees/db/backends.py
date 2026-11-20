"""Database backend selection and URL normalization."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.engine import URL, make_url

DatabaseBackend = Literal["sqlite", "postgresql"]


def get_database_backend(db_url: str | URL) -> DatabaseBackend:
    """Return the supported database backend for a SQLAlchemy URL."""
    url = make_url(db_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        return "sqlite"
    if backend == "postgresql":
        return "postgresql"

    raise ValueError(
        f"Unsupported database URL scheme {url.drivername!r}. "
        "Use a SQLite URL (sqlite:///...) or PostgreSQL URL "
        "(postgresql+psycopg://...)."
    )


def get_postgres_checkpoint_url(db_url: str | URL) -> str:
    """Return a psycopg-compatible URL for LangGraph's PostgreSQL saver."""
    if get_database_backend(db_url) != "postgresql":
        raise ValueError("A PostgreSQL database URL is required for PostgreSQL checkpoints.")

    url = make_url(db_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)
