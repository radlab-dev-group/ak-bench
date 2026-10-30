"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from akbench.core.errors import DatabaseError


def database_path_from_url(url: str) -> Path | None:
    """Extract a SQLite file path from a SQLAlchemy URL, if it is one."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    raw = url[len(prefix) :]
    if raw in (":memory:", ""):
        return None
    return Path(raw).expanduser()


def create_db_engine(url: str, *, echo: bool = False, timeout_seconds: int = 30) -> Engine:
    """Create an engine. SQLite gets foreign keys on and a sane busy timeout."""
    path = database_path_from_url(url)
    if path is not None and not path.is_absolute():
        raise DatabaseError(f"database path must be absolute: {path}")

    kwargs: dict[str, object] = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {
            "timeout": timeout_seconds,
            "check_same_thread": False,
        }
        if url.endswith(":memory:") or url == "sqlite://":
            kwargs["poolclass"] = StaticPool

    try:
        engine = create_engine(url, **kwargs)
    except Exception as exc:  # SQLAlchemy wraps many driver errors
        raise DatabaseError(f"cannot create engine for {url}: {exc}") from exc

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={int(timeout_seconds * 1000)}")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def engine_is_reachable(engine: Engine) -> None:
    """Raise :class:`DatabaseError` when the database does not answer."""
    from sqlalchemy import text

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise DatabaseError(f"database is not reachable: {exc}") from exc
