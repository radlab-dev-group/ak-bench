"""Cancelling a run, and an experiment, without pretending to be a scheduler.

The CLI is one-shot: ``akbench experiment run`` is the scheduler, and it is
only alive while it is running. Cancellation therefore has exactly two honest
shapes, and both are implemented here:

1. **In-process** — a :class:`CancelToken` the run loop checks between runs
   and passes to the orchestrator, which asks the agent to stop (the adapter's
   ``cancel``) while the in-flight run is finishing. ``Ctrl+C`` does this: the
   first press cancels, the second one leaves.
2. **Across processes** — ``akbench experiment cancel <uid>`` writes a marker
   file the running process polls (:class:`FileCancelSource`). There is no
   daemon to signal, and inventing one would be a scheduler this repository
   does not have; a file under the data directory is the whole IPC, and it is
   documented as such rather than disguised.

A cancelled run is a real outcome (``cancelled``), not an error: the agent was
asked to stop, the artifacts it left are kept, and the record says so.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from pathlib import Path


class CancelToken:
    """A thread-safe, one-way request to stop."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str | None = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str = "cancelled by the operator") -> None:
        if not self._event.is_set():
            self._reason = reason
            self._event.set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled; True when it happened, False on timeout."""
        return self._event.wait(timeout)


class FileCancelSource:
    """Watches a marker file so another process can cancel this one.

    ``akbench experiment cancel <uid>`` touches the file; the loop that polls
    it stops scheduling and asks the in-flight run to stop. Removing the file
    before a run starts clears the request, which is what a second ``cancel``
    on a finished experiment means.
    """

    def __init__(self, marker: Path) -> None:
        self.marker = Path(marker)
        self._token = CancelToken()
        self._watcher: threading.Thread | None = None

    @property
    def cancelled(self) -> bool:
        return self._token.cancelled

    @property
    def reason(self) -> str | None:
        return self._token.reason

    def poll(self) -> None:
        """One non-blocking check; the run loop calls this between runs."""
        if not self._token.cancelled and self.marker.exists():
            self._token.cancel("cancelled by `akbench experiment cancel`")

    def wait(self, timeout: float | None = None) -> bool:
        return self._token.wait(timeout)

    def watch(self, interval: float = 0.25, on_cancel: Callable[[], None] | None = None) -> None:
        """Watch in a background thread until cancelled or :meth:`stop`."""
        if self._watcher is not None:
            return
        state = {"stop": False}

        def _loop() -> None:
            while not state["stop"]:
                if not self._token.cancelled and self.marker.exists():
                    self._token.cancel("cancelled by `akbench experiment cancel`")
                    if on_cancel is not None:
                        with contextlib.suppress(Exception):
                            on_cancel()
                    return
                threading.Event().wait(interval)

        self._watcher = threading.Thread(target=_loop, daemon=True, name="akbench-cancel-watch")
        self._watcher.start()

    def stop(self) -> None:
        self._watcher = None


def cancel_marker_path(root: Path, experiment_uid: str) -> Path:
    """Where ``experiment cancel <uid>`` writes, under the data directory."""
    return Path(root) / "cancellations" / f"{experiment_uid}.cancel"


def install_cancellation_handlers(
    token: CancelToken, *, on_cancel: Callable[[], None] | None = None
) -> None:
    """First Ctrl+C cancels the token; the second one leaves as it always did.

    A one-shot CLI that dies on the first ``SIGINT`` loses the transition log
    of the run in flight and leaves the agent's process to the kernel. Neither
    is a result. The first press therefore asks the run to stop through the
    same token ``experiment cancel`` uses, and only the second press raises,
    which is what an operator holding the key down means.

    Registered only when there is a main thread to receive the signal; a call
    from a worker thread says nothing and changes nothing.
    """
    import signal

    def _handler(_signum: int, _frame: object) -> None:
        if not token.cancelled:
            token.cancel("interrupted (Ctrl+C)")
            if on_cancel is not None:
                on_cancel()
            return
        raise KeyboardInterrupt

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, _handler)
        except ValueError:
            return
