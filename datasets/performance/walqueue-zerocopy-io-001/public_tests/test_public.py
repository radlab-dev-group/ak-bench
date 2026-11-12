"""Time the write path the way the harness will, and keep the suite green."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared workspace")


ROOT = _source_root()


def test_the_repository_suite_passes():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_a_crash_at_a_hook_is_recoverable():
    sys.path.insert(0, str(ROOT / "src"))
    import tempfile

    from walqueue import InjectedCrash, Queue

    directory = Path(tempfile.mkdtemp())
    queue = Queue(directory)
    queue.put("kept", {"n": 1})
    owed = queue.export()
    queue.hook = lambda phase: (_ for _ in ()).throw(InjectedCrash(phase)) if phase == "append.payload" else None
    try:
        queue.put("lost", {"n": 2})
    except InjectedCrash:
        pass
    assert Queue(directory).export() == owed
