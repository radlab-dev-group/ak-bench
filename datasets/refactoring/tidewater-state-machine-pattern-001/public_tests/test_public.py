"""Run these before submitting: the trace check is the whole acceptance test."""

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


def test_reference_digests_still_match():
    completed = subprocess.run(
        [sys.executable, "tools/reference_traces.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_role_package_is_importable():
    sys.path.insert(0, str(ROOT / "src"))
    import tidewater.roles  # noqa: F401
