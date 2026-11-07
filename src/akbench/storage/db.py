"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def _redact(url: str) -> str:
    """The URL with its password removed, for anything a human or a log sees.

    Local to this module on purpose: the config layer has the same helper, and
    importing it here would make the storage layer depend on the layer that
    imports the storage layer.
    """
    if "://" not in url:
        return url
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except Exception:  # pragma: no cover - an unparseable URL has no password to hide
        return "<unparseable database URL>"


#: The shape of a namespace, restated here from the importer's rule rather than
#: imported: the importer depends on this module, so importing back would be a
#: cycle. The two patterns are checked against each other by a test.
SEARCH_PATH_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def _check_search_path(namespace: str) -> None:
    """Refuse a namespace the server could not read as one schema name."""
    if not SEARCH_PATH_PATTERN.match(namespace):
        raise DatabaseError(
            f"invalid namespace {namespace!r}: a schema name is a lower-case letter "
            "then letters, digits or underscores, at most 48 characters"
        )


def search_path_url(url: str, namespace: str | None) -> str:
    """The same connection pointed at one schema.

    PostgreSQL resolves an unqualified name through ``search_path``, so a
    namespace travels in the connection and every statement -- the migrations,
    a copy, a later read -- addresses it without qualifying anything.

    The namespace is checked because it is embedded in the libpq ``options``
    startup parameter, which the *server* parses into whitespace-separated
    tokens: a namespace holding a space would append further ``-c`` settings to
    the session, and a comma would silently repoint every unqualified table name
    in the application at somebody else's schema.
    """
    if not namespace:
        return url
    _check_search_path(namespace)
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    tokens = [
        token for token in query.get("options", "").split() if not token.startswith("-csearch_path")
    ]
    tokens.append(f"-csearch_path={namespace}")
    query["options"] = " ".join(tokens)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def namespace_of_url(url: str) -> str | None:
    """The namespace a URL points at, or ``None`` for the default schema."""
    query = dict(parse_qsl(urlsplit(url).query))
    for token in query.get("options", "").split():
        if token.startswith("-csearch_path="):
            return token.split("=", 1)[1]
    return None


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
    else:
        # A server-side connection can be closed underneath the pool by anything
        # between the two -- a restart, an idle timeout, a NAT entry expiring --
        # and a pooled socket handed out dead reads as a failure of the query.
        # Asking the server first costs one round trip per checkout. The pool is
        # bounded because a web UI now serves requests from several threads, and
        # an unbounded pool turns a slow database into a queue in front of a
        # database that is being hammered.
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5
        kwargs["pool_timeout"] = timeout_seconds

    try:
        engine = create_engine(url, **kwargs)
    except Exception as exc:  # SQLAlchemy wraps many driver errors
        # The URL carries the password; it is a credential that this message
        # would otherwise hand to whoever sees the traceback, the log line, or
        # the page that renders it.
        raise DatabaseError(
            f"cannot create engine for {_redact(url)}: {exc}"
        ) from exc

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
