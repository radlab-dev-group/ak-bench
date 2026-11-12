"""Measure the same way the hidden harness does, on the schedule the task names."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared workspace")


ROOT = _source_root()


def test_bench_reports_the_current_cost():
    completed = subprocess.run(
        [sys.executable, "tools/bench.py", "--schedule", "schedules/baseline-steady.json", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    record = json.loads(completed.stdout)
    print(f"cpu_seconds={record['cpu_seconds']} peak={record['traced_bytes_peak']}")
    assert record["violation"] is None


def test_reference_digests_still_match():
    completed = subprocess.run(
        [sys.executable, "tools/reference_traces.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
