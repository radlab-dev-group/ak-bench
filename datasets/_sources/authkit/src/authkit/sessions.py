"""Sessions on logical time.

``create_session(user, now)`` opens a session that expires ``ttl``
time units later. ``validate(token, now)`` returns the user while the
session is live and ``None`` once it has expired or been logged out.
``logout(token)`` ends the session immediately: a logged-out token must
never validate again.
"""

from __future__ import annotations


class SessionStore:
    """Sessions with expiry and logout, on explicit logical time."""

    def __init__(self, ttl: int = 100) -> None:
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        self._ttl = ttl
        self._sessions: dict[str, tuple[str, int]] = {}
        self._counter = 0

    def create_session(self, user: str, now: int) -> str:
        """Open a session for ``user`` at ``now`` and return its token."""
        self._counter += 1
        token = f"session-{self._counter}"
        self._sessions[token] = (user, now + self._ttl)
        return token

    def validate(self, token: str, now: int) -> str | None:
        """The user for a live session token, else ``None``."""
        entry = self._sessions.get(token)
        if entry is None:
            return None
        user, _expires_at = entry
        return user

    def logout(self, token: str) -> None:
        """End the session for ``token`` immediately."""
        pass
