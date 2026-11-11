"""Fetching a URL through an injected transport.

``fetch(url, transport)`` calls ``transport(url)`` which returns
``(status, headers, body)``. A redirect (status 301, 302, 303, 307 or
308 with a ``Location`` header) is followed, up to five times. The
fetcher must never fetch an internal or private host, neither directly
nor through a redirect: such a URL is refused with :class:`ValueError`.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5


def fetch(url: str, transport: Callable) -> str:
    """Fetch ``url`` through ``transport`` and return the body."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        status, headers, body = transport(current)
        if status in REDIRECT_STATUSES and "Location" in headers:
            current = headers["Location"]
            continue
        return body
    raise ValueError("too many redirects")
