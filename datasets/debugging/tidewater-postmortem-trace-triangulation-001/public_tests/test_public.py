"""Two checks you can run while you work: the clock contract, and the suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "tidewater").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared tidewater workspace")


ROOT = _source_root()
sys.path.insert(0, str(ROOT / "src"))


def test_re_skewing_a_clock_does_not_move_the_time_it_counted():
    from tidewater.clock import NodeClock

    clock = NodeClock()
    for _ in range(500):
        clock.tick()
    clock.set_skew(offset=200)
    assert clock.now >= 500, "a clock that had counted 500 ticks was moved back to 200"


def test_the_repository_suite_still_passes():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
