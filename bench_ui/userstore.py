"""The dashboard's own users, kept in the benchmark database as password hashes.

The users of the UI used to live in the process environment or a text file,
with the secrets in plain text beside the process that served them. Here they
are rows of the same database the runs live in, and a row never carries a
password — only ``pbkdf2_sha256$<iterations>$<salt>$<hash>``, a salted iterated
digest that proves a guess without ever showing the secret again. Bare sha256
would prove guesses too, and at a billion a second against a wordlist; PBKDF2
is the same idea with the work multiplied, which is what makes a stolen table
boring instead of fatal.

The module is also the command line the ``ui-user-add.sh`` script pipes its
password into — never as an argument, because argv is world-readable in ``ps``
and lands in the shell history of everyone who watched::

    printf '%s\\n' "$PASSWORD" | python3 -m bench_ui.userstore add alice admin
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError, ProgrammingError

from akbench.storage.db import create_db_engine, session_scope
from akbench.storage.models import UiUser

#: A table that is not there yet answers "no users" — the reads below are
#: fail-closed (nobody signs in) and quiet, so the app can start against a
#: database that has not been migrated yet and say so on the login page
#: rather than crash on the way up. The writes still fail loudly.
_NOT_THERE_YET = (OperationalError, ProgrammingError)

#: The digest scheme, named in every stored hash so a later scheme can be
#: introduced without guessing which rows are which.
SCHEME = "pbkdf2_sha256"
#: Work factor. High enough that a stolen table stays expensive to walk
#: through, low enough that signing in stays instant on a dashboard host.
ITERATIONS = 120_000
ROLES = ("viewer", "judge", "admin")
ROLE_DEFAULT = "viewer"

ENV_DATABASE_URL = "AKBENCH_UI_DATABASE_URL"
DEFAULT_DATABASE_PATH = "data/akbench.sqlite"


def database_url(
    environ: dict[str, str] | None = None, project_root: Path | None = None
) -> str:
    """The database the UI users live in — resolved the way the app resolves it.

    Precedence: an explicit ``AKBENCH_UI_DATABASE_URL``; then the project
    configuration — the ``.env`` with its ``AKBENCH_PG_*`` PostgreSQL
    parameters and ``AKBENCH_DB_BACKEND``, read by the very loader the
    dashboard and the CLI use — and only when that says nothing, the SQLite
    file a fresh checkout carries. A user written anywhere but where the app
    reads its users from would be worse than no user at all, so this walk is
    deliberately the app's own, not a second one that could drift.
    """
    env = os.environ if environ is None else environ
    explicit = (env.get(ENV_DATABASE_URL) or "").strip()
    if explicit:
        return explicit
    root = Path(project_root) if project_root else Path.cwd()
    try:
        from akbench.config.loader import load_settings, resolve_database_url
        from akbench.core.errors import ConfigError

        loaded = load_settings(None, project_root=root, environ=env)
        return resolve_database_url(loaded.settings, env)
    except ConfigError:
        # The configuration is unreadable — the same state that sends the
        # dashboard to its default SQLite file, so the same answer here.
        pass
    return f"sqlite:///{(root / DEFAULT_DATABASE_PATH).resolve()}"


def hash_password(secret: str, *, iterations: int = ITERATIONS) -> str:
    """The encoded digest of one secret: scheme, work, salt and answer."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), salt, iterations
    )
    return f"{SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(secret: str, encoded: str) -> bool:
    """Whether this secret is the one the stored hash was made from.

    A malformed row is ``False``, never an exception: a corrupted table must
    not become a crash on the login route.
    """
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != SCHEME:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            secret.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest_hex)


def create_user(engine: Any, name: str, secret: str, role: str = ROLE_DEFAULT) -> None:
    """One new row. The secret is hashed here and never kept anywhere else.

    Raises ``ValueError`` with the reason when the row would be a mistake:
    an empty name, an unknown role, an empty secret, or a name already taken.
    """
    name = (name or "").strip()
    role = (role or "").strip().lower()
    if not name:
        raise ValueError("the name is empty")
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    if not secret:
        raise ValueError("the password is empty")
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        existing = session.scalar(select(UiUser).where(UiUser.name == name))
        if existing is not None:
            raise ValueError(f"user '{name}' already exists")
        session.add(
            UiUser(
                name=name,
                password_hash=hash_password(secret),
                role=role,
                created_at=now,
                updated_at=now,
            )
        )


def find_user(engine: Any, name: str) -> tuple[str, str] | None:
    """``(role, password_hash)`` of one name, or ``None`` when it is not known."""
    try:
        with session_scope(engine) as session:
            row = session.scalar(select(UiUser).where(UiUser.name == name))
            return (row.role, row.password_hash) if row is not None else None
    except _NOT_THERE_YET:
        return None


def authenticate_user(engine: Any, name: str, secret: str) -> str | None:
    """The role these credentials prove, or ``None``.

    The stored hash is what answers; the password itself is never compared,
    never logged, and never leaves the caller.
    """
    found = find_user(engine, name)
    if found is None:
        return None
    role, encoded = found
    return role if verify_password(secret, encoded) else None


def role_of(engine: Any, name: str, issued_at: float | None = None) -> str | None:
    """The role of a name — what a session cookie resolves against.

    The cookie proves the name was signed in; the role is read from this table
    on every request, so a demoted user keeps a valid cookie and loses the
    privilege anyway. A cookie issued before this person's last sign-out is
    dead here too: signing out reaches the server, not only the browser.
    """
    found = find_user_with_cutoff(engine, name)
    if found is None:
        return None
    role, _encoded, cutoff = found
    if cutoff is not None and issued_at is not None:
        # SQLite hands timestamps back without their zone; what was written
        # was UTC, and read as local it would silently shift the line — an
        # hour off is exactly how a revoked cookie comes back to life.
        cutoff_utc = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
        if issued_at < cutoff_utc.timestamp():
            return None
    return role


def find_user_with_cutoff(
    engine: Any, name: str
) -> tuple[str, str, datetime | None] | None:
    """``(role, password_hash, session_cutoff)`` of one name, or ``None``."""
    try:
        with session_scope(engine) as session:
            row = session.scalar(select(UiUser).where(UiUser.name == name))
            if row is None:
                return None
            return (row.role, row.password_hash, row.session_cutoff)
    except _NOT_THERE_YET:
        return None


def revoke_sessions(engine: Any, name: str) -> None:
    """Sign this person out everywhere: every cookie issued until now is dead.

    The cookie is stateless, so the revocation has to live somewhere the
    cookie's signature cannot reach — this row. A name outside the table
    (an environment user) keeps the old meaning: their cookie dies when the
    jar lets go of it.
    """
    now = datetime.now(timezone.utc)
    try:
        with session_scope(engine) as session:
            session.execute(
                update(UiUser)
                .where(UiUser.name == name)
                .values(session_cutoff=now, updated_at=now)
            )
    except _NOT_THERE_YET:
        pass


def list_users(engine: Any) -> list[dict[str, Any]]:
    """Every user with their role — never their hash, which is not for pages."""
    with session_scope(engine) as session:
        rows = session.execute(
            select(UiUser.name, UiUser.role, UiUser.created_at).order_by(UiUser.name)
        ).all()
        return [
            {"name": name, "role": role, "created_at": created}
            for name, role, created in rows
        ]


def delete_user(engine: Any, name: str) -> bool:
    """Remove one name. ``False`` when there was no such name to remove."""
    with session_scope(engine) as session:
        result = session.execute(delete(UiUser).where(UiUser.name == name))
        return bool(result.rowcount)


def material(engine: Any) -> str:
    """Names and hashes, as material for the session-signing key.

    Derived from what is stored so the key survives a restart (nobody is
    signed out by a redeploy) and changes whenever the users change (a removed
    user's old cookie stops proving anything).
    """
    try:
        with session_scope(engine) as session:
            rows = session.execute(select(UiUser.name, UiUser.password_hash)).all()
        return "|".join(f"{name}\0{pw_hash}" for name, pw_hash in rows)
    except _NOT_THERE_YET:
        return ""


def main(argv: list[str] | None = None) -> int:
    """``add`` and ``delete`` for the script above; the secret arrives on stdin."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (2, 3) or args[0] not in ("add", "delete"):
        print(
            "usage: python3 -m bench_ui.userstore add <name> [role]   "
            "(secret on stdin; role: viewer | judge | admin)\n"
            "       python3 -m bench_ui.userstore delete <name>",
            file=sys.stderr,
        )
        return 2
    command, name = args[0], args[1]
    role = args[2] if len(args) == 3 else ROLE_DEFAULT
    url = database_url()
    engine = create_db_engine(url)
    try:
        if command == "add":
            secret = sys.stdin.readline().rstrip("\n")
            if not secret:
                raise ValueError("no password arrived on stdin")
            create_user(engine, name, secret, role)
            print(f"added '{name}' with role '{role}' to {url}")
        else:
            if not delete_user(engine, name):
                print(f"error: no user '{name}' in {url}", file=sys.stderr)
                return 1
            print(f"removed '{name}' from {url}")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
