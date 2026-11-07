"""Who may open the dashboard, how far, and under what headers.

The dashboard used to answer anyone who could reach the port. That was fine
while it only ever bound ``127.0.0.1`` on a laptop, and it is not fine for a
deployment anyone on a network can reach, because the history it shows is not
public: run logs, task code, and -- until this module existed -- the hidden
tests and the planted defect of every task, which is the answer key of the
benchmark.

Two decisions shape this file.

*Fail closed at the boundary that is actually exposed.* A loopback bind is a
developer's machine and stays open; anything else demands credentials, and a
missing user list is a startup error rather than an open door. A host the app
cannot classify counts as exposed, because guessing "private" wrongly is the
expensive mistake.

*The answer key is a separate privilege from the scoreboard.* A reader shown
how the benchmark scored the runs should not thereby be handed the hidden tests
and the mutation patch. That split is a role, not a page.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Sees the runs, the scores, the charts. This is what a reader gets.
VIEWER = "viewer"
#: Additionally sees what would let someone pass a task without doing it: the
#: hidden tests, the planted defect, and the archive that carries both.
JUDGE = "judge"

ROLES: tuple[str, ...] = (VIEWER, JUDGE)

#: The recorded file kinds that are the answer key rather than the task.
GROUND_TRUTH_KINDS: frozenset[str] = frozenset({"hidden_tests", "mutation"})

ENV_PREFIX = "AKBENCH_UI_"
ENV_AUTH = f"{ENV_PREFIX}AUTH"
ENV_USERS = f"{ENV_PREFIX}USERS"
ENV_USERS_FILE = f"{ENV_PREFIX}USERS_FILE"
ENV_JUDGE_USERS = f"{ENV_PREFIX}JUDGE_USERS"
ENV_REALM = f"{ENV_PREFIX}REALM"
ENV_BIND_HOST = f"{ENV_PREFIX}BIND_HOST"
ENV_USER_HEADER = f"{ENV_PREFIX}USER_HEADER"
ENV_CSP = f"{ENV_PREFIX}CSP"
ENV_SHOW_GROUND_TRUTH = f"{ENV_PREFIX}SHOW_GROUND_TRUTH"

#: The addresses that mean "this box only". Binding any of these still lets a
#: local process in, which is the accepted trust model of a developer machine.
#: An *unset* address is deliberately not one of them: not knowing where the
#: socket went is not evidence that it went nowhere.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

DEFAULT_REALM = "AK-Bench"

#: ``script-src`` keeps ``'unsafe-inline'``: the templates carry inline handler
#: attributes (``onclick="openRunModal(...)"``) and inline chart bootstrap, and
#: removing them is a template rewrite this module deliberately does not attempt.
#: What the policy does buy is that nothing loads from another origin -- the
#: Chart.js CDN, whose removal closes a script-injection path no amount of
#: output escaping would -- and that nothing is framed, posted, or fetched off
#: to a foreign host.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'"
)

#: Headers every response carries. ``X-Frame-Options`` is the older twin of
#: ``frame-ancestors`` and stays for a proxy that reads only the former.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityConfigError(Exception):
    """The security configuration says two things at once, or nothing useful."""


@dataclass(frozen=True)
class User:
    """One operator: the name they type, the secret they prove, what they see."""

    name: str
    secret: str
    role: str = VIEWER

    def verify(self, candidate: str) -> bool:
        """Constant-time, so a caller cannot walk the secret one byte at a time."""
        return hmac.compare_digest(
            self.secret.encode("utf-8"), candidate.encode("utf-8")
        )


@dataclass(frozen=True)
class Identity:
    """An authenticated caller, as the request carries it downstream."""

    name: str
    role: str

    @property
    def is_judge(self) -> bool:
        return self.role == JUDGE


@dataclass(frozen=True)
class SecuritySettings:
    """The resolved security posture of one running dashboard.

    ``enabled`` off is not "no security", it is "this is a loopback developer
    instance": every caller is then a judge, which is what the single-user
    command line has always assumed.
    """

    enabled: bool
    users: tuple[User, ...] = ()
    judge_users: frozenset[str] = frozenset()
    realm: str = DEFAULT_REALM
    bind_host: str = ""
    user_header: str | None = None
    csp: str = DEFAULT_CSP
    #: ``auto`` (judges only when auth is on), ``always``, or ``never``.
    ground_truth: str = "auto"
    #: Anything that went wrong while reading the environment, kept as a value
    #: rather than raised because ``bench_ui.app`` builds the app at import time
    #: -- that is how uvicorn loads an import string -- and a module that cannot
    #: be imported cannot report anything. The command line fails fast on it
    #: instead; a served app refuses every request.
    load_errors: str | None = None

    @property
    def misconfiguration(self) -> str | None:
        """Why this posture cannot serve anyone, computed rather than remembered.

        A property so that the rule cannot be stepped around by whoever builds
        the object: a settings value with authentication on and nobody in it is
        misconfigured however it was constructed, and a stored flag could be
        simply left out.
        """
        problems = []
        if self.load_errors:
            problems.append(self.load_errors)
        if self.enabled and not self.users and not self.user_header:
            problems.append(
                "authentication is on but nobody is configured: set "
                f"{ENV_USERS}='name:secret[:role],...' or "
                f"{ENV_USERS_FILE}=/path/to/users (one entry per line), or "
                f"{ENV_USER_HEADER}='X-Forwarded-User' behind a proxy that "
                "authenticates and overwrites that header"
            )
        return "; ".join(problems) if problems else None

    def role_for(self, name: str) -> str:
        """The role a name gets: its own if listed, judge if named as one."""
        for user in self.users:
            if user.name == name:
                return user.role
        return JUDGE if name in self.judge_users else VIEWER

    def shows_ground_truth(self, identity: Identity | None) -> bool:
        """Whether this caller may see hidden tests and the planted defect."""
        if self.ground_truth == "always":
            return True
        if self.ground_truth == "never":
            return False
        if not self.enabled:
            return True
        return bool(identity and identity.is_judge)

    def describe(self) -> str:
        if self.misconfiguration:
            return f"refusing requests: {self.misconfiguration}"
        if not self.enabled:
            return "off (loopback instance: every caller is trusted)"
        names = ", ".join(f"{u.name}:{u.role}" for u in self.users) or "none"
        via = f" via {self.user_header}" if self.user_header else " via HTTP Basic"
        return f"on{via}; users: {names}"


def is_loopback(host: str | None) -> bool:
    """Whether a bind address is reachable only from this machine."""
    if host is None:
        return False
    cleaned = host.strip().strip("[]").lower()
    if cleaned in LOOPBACK_HOSTS:
        return True
    # 127.0.0.0/8 is loopback in its whole extent, not just .1
    return cleaned.startswith("127.")


def _split_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_user(spec: str) -> User:
    """One ``name:secret[:role]`` entry.

    Secrets may contain ``:``: the role is recognised only when the final
    segment names one, so ``analyst:a:b:c`` is a three-part secret rather than a
    truncated one.
    """
    parts = spec.split(":")
    if len(parts) < 2:
        raise SecurityConfigError(
            f"user entry {spec!r} needs the form name:secret[:role]"
        )
    name = parts[0].strip()
    if not name:
        raise SecurityConfigError(f"user entry {spec!r} has an empty name")
    role = VIEWER
    body = parts[1:]
    if len(body) >= 2 and body[-1].strip().lower() in ROLES:
        role = body[-1].strip().lower()
        body = body[:-1]
    secret = ":".join(body)
    if not secret:
        raise SecurityConfigError(f"user {name!r} has an empty secret")
    return User(name=name, secret=secret, role=role)


def parse_users(raw: str | None) -> tuple[User, ...]:
    entries = _split_list(raw)
    users = tuple(parse_user(entry) for entry in entries)
    seen: set[str] = set()
    for user in users:
        if user.name in seen:
            raise SecurityConfigError(f"user {user.name!r} is configured twice")
        seen.add(user.name)
    return users


def read_users_file(path: Path) -> tuple[User, ...]:
    """The same entries, one per line, from a file.

    A file rather than a variable because a command line is world-readable in
    ``ps`` and inherited into every child process, and an operator pasting a
    deployment command into a shell history has published their dashboard
    password to everyone on the box.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SecurityConfigError(f"cannot read {ENV_USERS_FILE}: {exc}") from exc
    users: list[User] = []
    for line in text.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        users.append(parse_user(entry))
    return tuple(users)


def load_security_settings(
    environ: dict[str, str] | None = None,
) -> SecuritySettings:
    """Resolve the ``AKBENCH_UI_*`` environment into a posture.

    ``AKBENCH_UI_AUTH`` takes ``on``, ``off``, or ``auto`` (the default).
    ``auto`` enables authentication unless the bind address is loopback, which
    keeps ``./run-ui.sh`` working on a laptop while making any real deployment
    ask for a name and a secret.

    Nothing here raises. A dashboard that has been told to authenticate but has
    no users records that as :attr:`SecuritySettings.misconfiguration` and then
    refuses every request, which is both fail closed and diagnosable; raising
    instead would break the import of ``bench_ui.app``, and an unimportable
    module reports nothing at all. :func:`require_valid_security` is the
    fail-fast half, for the command line.
    """
    env = os.environ if environ is None else environ
    problems: list[str] = []

    bind_host = env.get(ENV_BIND_HOST, "").strip()
    mode = (env.get(ENV_AUTH) or "auto").strip().lower()
    if mode in {"off", "false", "0"}:
        enabled = False
    elif mode in {"on", "true", "1"}:
        enabled = True
    elif mode == "auto":
        enabled = not is_loopback(bind_host)
    else:
        enabled = True
        problems.append(
            f"{ENV_AUTH} must be on, off or auto, not {mode!r}; refusing to serve"
        )

    users: tuple[User, ...] = ()
    try:
        users = parse_users(env.get(ENV_USERS))
    except SecurityConfigError as exc:
        problems.append(str(exc))

    users_file = env.get(ENV_USERS_FILE)
    if users_file and not problems:
        try:
            from_file = read_users_file(Path(users_file).expanduser())
        except SecurityConfigError as exc:
            problems.append(str(exc))
            from_file = ()
        known = {user.name for user in users}
        users = users + tuple(u for u in from_file if u.name not in known)

    judge_users = frozenset(_split_list(env.get(ENV_JUDGE_USERS)))
    realm = (env.get(ENV_REALM) or DEFAULT_REALM).strip() or DEFAULT_REALM
    header = (env.get(ENV_USER_HEADER) or "").strip() or None
    csp = env.get(ENV_CSP)
    csp = DEFAULT_CSP if csp is None else csp.strip()

    ground_truth = (env.get(ENV_SHOW_GROUND_TRUTH) or "auto").strip().lower()
    if ground_truth not in {"auto", "always", "never"}:
        problems.append(
            f"{ENV_SHOW_GROUND_TRUTH} must be auto, always or never, "
            f"not {ground_truth!r}"
        )

    return SecuritySettings(
        enabled=enabled,
        users=users,
        judge_users=judge_users,
        realm=realm,
        bind_host=bind_host,
        user_header=header,
        csp=csp,
        ground_truth=ground_truth,
        load_errors="; ".join(problems) if problems else None,
    )


def require_valid_security(settings: SecuritySettings) -> SecuritySettings:
    """The fail-fast half, for a command line that has not bound a socket yet."""
    if settings.misconfiguration:
        raise SecurityConfigError(settings.misconfiguration)
    return settings


def _decode_basic(header_value: str) -> tuple[str, str] | None:
    scheme, _, encoded = header_value.partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    name, sep, secret = decoded.partition(":")
    if not sep:
        return None
    return name, secret


def authenticate(
    settings: SecuritySettings, headers: dict[str, str]
) -> Identity | None:
    """The caller behind these headers, or ``None`` when there is no such caller.

    ``headers`` are lower-cased, as an ASGI scope carries them.
    """
    if not settings.enabled:
        # A loopback instance has one trusted caller and they see everything,
        # which is what the command line has always done.
        return Identity(name="local", role=JUDGE)

    if settings.user_header:
        # A proxy in front has already authenticated; it overwrites this header,
        # and the deployment is only sound if it does.
        name = headers.get(settings.user_header.lower(), "").strip()
        if not name:
            return None
        return Identity(name=name, role=settings.role_for(name))

    credentials = _decode_basic(headers.get("authorization", ""))
    if credentials is None:
        return None
    name, secret = credentials
    for user in settings.users:
        # Compare the name in constant time too: the set of valid names is
        # itself a secret when it encodes people.
        name_matches = hmac.compare_digest(
            user.name.encode("utf-8"), name.encode("utf-8")
        )
        if name_matches and user.verify(secret):
            return Identity(name=user.name, role=user.role)
    return None


def authorization_challenge(realm: str) -> str:
    """The ``WWW-Authenticate`` value that makes a browser show a login box."""
    return f'Basic realm="{realm}", charset="UTF-8"'


def fingerprint(settings: SecuritySettings) -> str:
    """A short, non-reversible mark of the configuration, for logs."""
    digest = hashlib.sha256(
        f"{settings.enabled}|{len(settings.users)}|{settings.realm}".encode()
    ).hexdigest()[:12]
    return digest


def public_paths(path: str, extra: Iterable[str] = ()) -> bool:
    """Paths served before a caller has proved anything.

    The static bundle carries no history, only CSS and JavaScript, and a browser
    fetching it before the login box appears keeps the stylesheets from flashing
    unstyled markup.
    """
    if path.startswith("/static/"):
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in extra)


def identity_from_scope(scope: dict[str, Any]) -> Identity | None:
    """The identity a middleware stored on the request, if any."""
    state = scope.get("state") or {}
    name = state.get("akbench_user")
    if not name:
        return None
    return Identity(name=str(name), role=str(state.get("akbench_role", VIEWER)))


def request_shows_ground_truth(request: Any, settings: SecuritySettings) -> bool:
    """Ask the question a handler actually has: may this reader see the key?

    Takes the starlette ``Request`` so a handler can pass what it already has.
    """
    scope = getattr(request, "scope", None) or {}
    cached = (scope.get("state") or {}).get("akbench_shows_ground_truth")
    if isinstance(cached, bool):
        return cached
    shows = settings.shows_ground_truth(identity_from_scope(scope))
    scope.setdefault("state", {})["akbench_shows_ground_truth"] = shows
    return shows
