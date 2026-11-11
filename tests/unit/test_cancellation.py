"""The cancellation primitives: a token, a file, and the path between them.

The CLI is one-shot, so cancel is not a signal to a daemon; it is a token the
run loop shares with the orchestrator and a marker file another process of the
same installation writes. Both are small enough to test directly, and both are
the whole of what ``experiment cancel`` can honestly promise.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from akbench.orchestration.cancellation import (
    CancelToken,
    FileCancelSource,
    cancel_marker_path,
)


def test_a_token_starts_uncancelled_and_keeps_the_first_reason() -> None:
    token = CancelToken()
    assert token.cancelled is False
    assert token.reason is None

    token.cancel("operator asked")
    token.cancel("a second, louder request")

    assert token.cancelled is True
    assert token.reason == "operator asked", "the first reason is the cancellation"


def test_wait_returns_as_soon_as_the_token_fires() -> None:
    token = CancelToken()

    threading.Timer(0.05, lambda: token.cancel("late")).start()
    fired = token.wait(timeout=5.0)

    assert fired is True


def test_wait_reports_a_timeout_as_false() -> None:
    token = CancelToken()
    assert token.wait(timeout=0.05) is False


def test_a_marker_file_cancels_the_source_that_watches_it(tmp_path: Path) -> None:
    marker = tmp_path / "cancellations" / "exp-1.cancel"
    source = FileCancelSource(marker)
    source.poll()
    assert source.cancelled is False

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("now\n", encoding="utf-8")
    source.poll()

    assert source.cancelled is True
    assert "cancel" in (source.reason or "")


def test_the_watcher_notices_a_marker_written_by_another_thread(tmp_path: Path) -> None:
    marker = tmp_path / "exp-2.cancel"
    source = FileCancelSource(marker)
    seen = threading.Event()
    source.watch(interval=0.02, on_cancel=seen.set)

    threading.Timer(0.05, lambda: marker.write_text("now\n", encoding="utf-8")).start()

    assert seen.wait(5.0) is True
    assert source.cancelled is True
    source.stop()


def test_a_source_without_a_marker_never_fires(tmp_path: Path) -> None:
    source = FileCancelSource(tmp_path / "nobody-writes-this.cancel")
    source.watch(interval=0.02)
    time.sleep(0.1)
    assert source.cancelled is False
    source.stop()


def test_the_marker_lives_under_the_data_directory(tmp_path: Path) -> None:
    marker = cancel_marker_path(tmp_path / "data", "exp-42")
    assert marker == tmp_path / "data" / "cancellations" / "exp-42.cancel"
