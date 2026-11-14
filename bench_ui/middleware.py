"""ASGI middleware: security headers on every response, credentials before any history.

Written against the raw ASGI interface rather than ``BaseHTTPMiddleware`` for
one reason: this app now spends most of its time doing synchronous database
work in a worker thread, and a streaming middleware in that path buffers
responses. Wrapping ``send`` costs one function call and sees every response,
including the 404 Starlette produces for a path that does not exist.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from typing import Any

from bench_ui.security import (
    SECURITY_HEADERS,
    SecuritySettings,
    authenticate,
    authorization_challenge,
    public_paths,
    session_identity,
    session_key,
)

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: A login refusal that names no path and echoes no input: everything a caller
#: learns from it they could learn from the HTTP status alone.
_UNAUTHENTICATED_BODY = (
    b"<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    b"<title>AK-Bench: sign in required</title></head><body>"
    b"<h1>AK-Bench &mdash; sign in required</h1>"
    b"<p>This dashboard shows benchmark history, so it asks who is asking."
    b"</p></body></html>"
)


def _header_pairs(raw: Sequence[tuple[bytes, bytes]]) -> dict[str, str]:
    """ASGI headers, lower-cased and joined the way :class:`Request.headers` does."""
    joined: dict[str, str] = {}
    for name, value in raw:
        key = name.decode("latin-1").lower()
        if key in joined:
            joined[key] = f"{joined[key]}, {value.decode('latin-1')}"
        else:
            joined[key] = value.decode("latin-1")
    return joined


class SecurityMiddleware:
    """Applies :class:`SecuritySettings` to an HTTP request and its response."""

    def __init__(
        self,
        app: ASGIApp,
        settings: SecuritySettings,
        *,
        extra_public: Sequence[str] = (),
        user_resolver: Any = None,
        session_secret: bytes | None = None,
    ) -> None:
        self.app = app
        self.settings = settings
        self.user_resolver = user_resolver
        self.session_key = (
            session_secret if session_secret is not None else session_key(settings)
        )
        self.extra_public = tuple(extra_public)
        self.headers = dict(SECURITY_HEADERS)
        if settings.csp:
            self.headers["Content-Security-Policy"] = settings.csp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if public_paths(path, self.extra_public):
            await self.app(scope, receive, self._send_with_headers(send, {}))
            return

        if self.settings.misconfiguration:
            # Asked to authenticate, given nobody to authenticate as. Saying so
            # beats a login box that can never be satisfied.
            await self._refuse(send)
            return

        headers = _header_pairs(scope.get("headers", []))
        identity = authenticate(self.settings, headers, self.user_resolver)
        if identity is None:
            # No Basic credentials and no proxy header: a browser may still be
            # carrying the cookie the login page handed it.
            identity = session_identity(
                headers.get("cookie", ""),
                self.settings,
                self.session_key,
                self.user_resolver,
            )
        if identity is None:
            # A browser is shown the login page -- the credential box cannot
            # explain itself and cannot be signed out of. A script keeps the
            # 401 challenge it has always understood.
            if scope.get("method") == "GET" and "text/html" in headers.get("accept", ""):
                await self._to_login(send, scope.get("path", ""))
                return
            await self._reject(send)
            return

        state = dict(scope.get("state") or {})
        state["akbench_user"] = identity.name
        state["akbench_role"] = identity.role
        scope["state"] = state

        # A page behind credentials must not be readable from a shared or
        # cached browser context afterwards.
        extra = {"Cache-Control": "no-store"}
        await self.app(scope, receive, self._send_with_headers(send, extra))

    def _send_with_headers(
        self, send: Send, extra: dict[str, str]
    ) -> Callable[[dict[str, Any]], Awaitable[None]]:
        async def wrapped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {name.decode("latin-1").lower() for name, _ in headers}
                for name, value in {**self.headers, **extra}.items():
                    if name.lower() not in existing:
                        headers.append((name.lower().encode("latin-1"), value.encode()))
                message["headers"] = headers
            await send(message)

        return wrapped

    async def _refuse(self, send: Send) -> None:
        """503: the configuration asked for a gate and did not build one."""
        body = (
            b"<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            b"<title>AK-Bench: misconfigured</title></head><body>"
            b"<h1>AK-Bench &mdash; misconfigured</h1><p>Authentication is on but "
            b"no users are configured, so this dashboard serves nothing. The "
            b"remedy is in the server log.</p></body></html>"
        )
        headers = [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
        ]
        for name, value in self.headers.items():
            headers.append((name.lower().encode("latin-1"), value.encode()))
        await send({"type": "http.response.start", "status": 503, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _to_login(self, send: Send, path: str) -> None:
        """303 to the login page, remembering where the caller was headed."""
        from urllib.parse import quote

        location = f"/login?next={quote(path or '/', safe='')}"
        headers = [(b"location", location.encode("latin-1")), (b"content-length", b"0")]
        for name, value in self.headers.items():
            headers.append((name.lower().encode("latin-1"), value.encode()))
        await send({"type": "http.response.start", "status": 303, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    async def _reject(self, send: Send) -> None:
        headers = [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"content-length", str(len(_UNAUTHENTICATED_BODY)).encode()),
            (
                b"www-authenticate",
                authorization_challenge(self.settings.realm).encode("latin-1"),
            ),
        ]
        for name, value in self.headers.items():
            headers.append((name.lower().encode("latin-1"), value.encode()))
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHENTICATED_BODY})
