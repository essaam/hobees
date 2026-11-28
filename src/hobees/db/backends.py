"""Database backend selection and URL normalization."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.engine import URL, make_url

DatabaseBackend = Literal["sqlite", "postgresql"]

#: What `str(url)` / `f"{url}"` writes in place of the password. Once a URL is stringified
#: that becomes the password, so a checkpointer built from the string authenticates with
#: `***` and PostgreSQL answers `password authentication failed` even though the engine
#: connects with the real value.
MASKED_PASSWORD = "***"


def render_db_url(db_url: str | URL) -> str:
    """Render a database URL with its password intact.

    Takes either a string or a SQLAlchemy `URL`. A `URL` must never be turned into text
    with `str()`/f-string on the way to a connection: that is what drops the password.
    """
    url = make_url(db_url)
    if url.password == MASKED_PASSWORD:
        raise ValueError(
            "the database URL has the masked password '***': it was stringified with "
            "str(url)/f-string instead of render_as_string(hide_password=False), so the "
            "real password is already lost at this point. Pass the URL object, or "
            "render_db_url(db_url)."
        )
    return url.render_as_string(hide_password=False)


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
    """Return a psycopg-compatible URL for LangGraph's PostgreSQL saver.

    Only the driver name changes; the password is kept. A URL that already arrived here
    masked is rejected with the reason, because a `***` password can never authenticate.
    """
    if get_database_backend(db_url) != "postgresql":
        raise ValueError("A PostgreSQL database URL is required for PostgreSQL checkpoints.")

    url = make_url(db_url).set(drivername="postgresql")
    if url.password == MASKED_PASSWORD:
        raise ValueError(
            "cannot build a PostgreSQL checkpoint URL from the masked password '***': "
            "the URL was stringified before it got here. Pass the URL object itself "
            "(engine.url / session.bind.url) or render it with render_db_url(), since "
            "render_as_string(hide_password=False) can only recover a password that is "
            "still stored on the URL."
        )
    return url.render_as_string(hide_password=False)


__all__ = [
    "DatabaseBackend",
    "MASKED_PASSWORD",
    "get_database_backend",
    "get_postgres_checkpoint_url",
    "render_db_url",
]
