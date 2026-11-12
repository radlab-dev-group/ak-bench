"""Time a workspace's write path against the seed's, the same way, twice each.

`reference/walqueue` is an untouched copy of the package as the task ships it.
Both sides run the same script with the same workload, best of a few repeats,
measured with `time.process_time` so the machine's other business is not billed
to the queue.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCE = HERE / "reference"

RUNNER = """
import json, pathlib, sys, tempfile, time

sys.path.insert(0, sys.argv[1])
from walqueue import Queue

tasks = int(sys.argv[2])
best = None
for _ in range(int(sys.argv[3])):
    directory = pathlib.Path(tempfile.mkdtemp())
    started = time.process_time()
    queue = Queue(directory)
    for index in range(tasks):
        queue.put(f"t{index}", {"payload": f"value-{index}", "n": index})
    for index in range(0, tasks, 2):
        (lease,) = queue.reserve(f"w{index % 7}", now=index, lease_seconds=10)
        queue.ack(lease, now=index)
    queue.compact()
    elapsed = time.process_time() - started
    best = elapsed if best is None else min(best, elapsed)
    recovered = Queue(directory)
    stats = recovered.stats()
print(json.dumps({"seconds": best, "done": stats["done"], "ready": stats["ready"],
                  "sequence": recovered.sequence}))
"""


def _measure(package_root: Path, tasks: int, repeats: int) -> dict:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", RUNNER, str(package_root), str(tasks), str(repeats)],
        cwd=HERE,
        env=environment,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"the benchmark failed against {package_root}:\n{completed.stderr}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def measure(tasks: int = 400, repeats: int = 2) -> tuple[dict, dict]:
    """(candidate, reference) for the same workload."""
    candidate = _measure(HERE.parent / "src", tasks, repeats)
    reference = _measure(REFERENCE, tasks, repeats)
    assert candidate["done"] == reference["done"] and candidate["sequence"] == reference["sequence"], (
        "the optimised queue did not process the same workload: "
        f"{candidate} against {reference}"
    )
    return candidate, reference
