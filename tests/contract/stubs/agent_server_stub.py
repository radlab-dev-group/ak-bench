"""A stub agent server: the AK-Bench HTTP protocol, minus an agent.

It exists so the HTTP adapter can be tested against a socket rather than a
mock, which is the only way to prove the protocol as documented in
``docs/AGENT_ADAPTERS.md`` is actually implementable. Behaviour is selected
when the server is constructed, and every request it receives is recorded so a
test can assert what the adapter really sent.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

BEHAVIOURS = ("complete", "fail", "hang", "infrastructure_error", "no_cancel")

#: What state a freshly accepted task lands in, per behaviour. A real server
#: finishes asynchronously; the stub answers the first status query already
#: settled, except for ``hang``, which is the point of that behaviour.
#: ``no_cancel`` keeps running and refuses the cancellation with 405.
STATE_AFTER_ACCEPT = {
    "complete": "completed",
    "fail": "failed",
    "hang": "running",
    "infrastructure_error": "infrastructure_error",
    "no_cancel": "running",
}

#: session id handed out for one behaviour; the stub holds one run at a time.
SESSION_ID = "stub-session-1"


class StubAgentServer:
    """A one-run agent server on a loopback port."""

    def __init__(
        self,
        behaviour: str = "complete",
        *,
        version: str | None = "stub-agent 1.0",
        report_usage: bool = True,
    ):
        if behaviour not in BEHAVIOURS:
            raise ValueError(f"unknown stub behaviour {behaviour!r}, expected one of {BEHAVIOURS}")
        self.behaviour = behaviour
        self.version = version
        self.report_usage = report_usage
        self.state = "pending"
        self.detail: str | None = None
        self.requests: list[dict[str, Any]] = []
        self.cancelled = False
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None, "the stub server is not running"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> StubAgentServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence the test output
                pass

            def _send(self, status: int, payload: dict[str, Any] | None) -> None:
                body = b"" if payload is None else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                return json.loads(raw) if raw else {}

            def _record(self, method: str, body: dict[str, Any]) -> None:
                outer.requests.append(
                    {"method": method, "path": self.path, "body": body,
                     "authorization": self.headers.get("Authorization")}
                )

            def do_GET(self) -> None:
                path = urllib.parse.urlsplit(self.path).path
                self._record("GET", {})
                if path == "/version":
                    self._send(200, {"version": outer.version} if outer.version else {})
                    return
                if path == f"/sessions/{SESSION_ID}":
                    self._send(200, {"state": outer.state, "detail": outer.detail})
                    return
                if path == f"/sessions/{SESSION_ID}/result":
                    self._send(200, outer.result_payload())
                    return
                self._send(404, {"detail": f"no such path: {path}"})

            def do_POST(self) -> None:
                path = urllib.parse.urlsplit(self.path).path
                body = self._body()
                self._record("POST", body)
                if path == "/tasks":
                    if not (body.get("task") or "").strip():
                        self._send(422, {"detail": "task text is empty"})
                        return
                    outer.state = STATE_AFTER_ACCEPT[outer.behaviour]
                    self._send(201, {"session_id": SESSION_ID})
                    return
                if path == f"/sessions/{SESSION_ID}/cancel":
                    if outer.behaviour == "no_cancel":
                        self._send(405, {"detail": "cancellation is not supported"})
                        return
                    outer.cancelled = True
                    outer.state = "cancelled"
                    self._send(200, {"state": "cancelled"})
                    return
                self._send(404, {"detail": f"no such path: {path}"})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def finish(self, state: str) -> None:
        """Move the run to a terminal state, as a real server would on completion."""
        self.state = state

    def result_payload(self) -> dict[str, Any]:
        return {
            "status": self.state,
            "final_message": f"stub finished as {self.state}",
            "exit_code": 0 if self.state == "completed" else 1,
            "workspace_changes": ["changed_by_server.py"],
            "observations": {"server": "stub", "tool_call_count": 3},
            "artifacts": {"server_log": "stub.log"},
            "token_usage": (
                {"input_tokens": 21, "output_tokens": 9, "total_tokens": 30}
                if self.report_usage
                else None
            ),
        }

    def __enter__(self) -> StubAgentServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


__all__ = ["BEHAVIOURS", "SESSION_ID", "StubAgentServer"]
