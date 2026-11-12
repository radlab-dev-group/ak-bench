"""Measure a workspace the way the repository measures a run.

The candidate and the reference are timed by the same script, in the same way,
one after the other: ``time.process_time`` for CPU the process actually used,
``tracemalloc`` for the memory the run itself allocated, the best of a few
repeats so a scheduler hiccup cannot decide the outcome. Comparing the two
inside one evaluation is what makes the target a ratio rather than a wall-clock
number that belongs to whichever machine ran the tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REFERENCE = HERE / "reference"
SCHEDULES = ROOT / "schedules"

#: The schedules the harness measures. They are the expensive ones in the
#: corpus: the long haul, a partition storm, and a crash chain, so an
#: optimisation cannot win by being fast at nothing.
MEASURED = ("baseline-steady", "long-haul", "partition-heal-storm")

RUNNER = """
import gc, json, sys, time, tracemalloc

sys.path.insert(0, sys.argv[1])
from tidewater.cluster import Cluster
from tidewater.schedule import load_schedule

package, schedule_path, repeats = sys.argv[1], sys.argv[2], int(sys.argv[3])
best_cpu = None
best_peak = None
digest = None
for _ in range(repeats):
    schedule = load_schedule(schedule_path)
    gc.collect()
    tracemalloc.start()
    started = time.process_time()
    result = Cluster(schedule).run()
    cpu = time.process_time() - started
    _live, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    best_cpu = cpu if best_cpu is None else min(best_cpu, cpu)
    best_peak = peak if best_peak is None else min(best_peak, peak)
    digest = result.digest
print(json.dumps({"cpu": best_cpu, "peak": best_peak, "digest": digest,
                  "ok": result.ok, "events": result.events}))
"""


def measure(package_root: Path, schedule: str, repeats: int = 2) -> dict:
    """Time one schedule against one package root, best of ``repeats`` runs."""

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", RUNNER, str(package_root), str(SCHEDULES / f"{schedule}.json"), str(repeats)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"the benchmark could not run against {package_root}:\n{completed.stdout}\n{completed.stderr}"
        )
    record = json.loads(completed.stdout.strip().splitlines()[-1])
    record["schedule"] = schedule
    return record


def candidate_and_reference(schedule: str, repeats: int = 2) -> tuple[dict, dict]:
    return measure(ROOT / "src", schedule, repeats), measure(REFERENCE, schedule, repeats)
