"""Small stdlib HTTP helper for runtime adapters.

Stdlib only, deliberately: the runtime layer must not add a dependency for a
handful of GET requests, and the responses it reads are small. Timeouts are
mandatory — a benchmark must never hang on a health endpoint.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT = 10.0
USER_AGENT = "ak-bench/runtime-manager"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


class HttpError(Exception):
    """The request could not be completed at all (DNS, refused, timeout)."""


def get_json(
    url: str,
    *,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    """GET ``url`` and return the response, raising only on transport failures.

    HTTP error codes are returned, not raised: an adapter must be able to tell
    "the endpoint refuses us" (403, a fact about the interface) apart from
    "the host is unreachable" (a fact about the environment).
    """
    request = urllib.request.Request(url, method="GET")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json, text/plain, */*")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return HttpResponse(
                status=response.status,
                body=payload,
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return HttpResponse(status=exc.code, body=payload)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpError(f"{url}: {exc}") from exc
