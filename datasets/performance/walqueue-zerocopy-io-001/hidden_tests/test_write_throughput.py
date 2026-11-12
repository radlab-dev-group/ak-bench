"""The write path, timed against the seed.

The target is a ratio, measured on the machine running the tests, against an
untouched copy of the package shipped inside this task. The state clone alone is
an order of magnitude at this workload, so the bar is where a real fix lands
rather than where a marginal one does.
"""

from __future__ import annotations

from bench_harness import measure

CPU_TARGET = 0.30


def test_the_write_path_gets_much_faster():
    candidate, reference = measure(tasks=400, repeats=2)
    ratio = candidate["seconds"] / reference["seconds"]
    assert ratio <= CPU_TARGET, (
        f"the workload took {candidate['seconds']:.3f}s against a baseline of "
        f"{reference['seconds']:.3f}s: {ratio:.0%} of it, and the target is {CPU_TARGET:.0%}"
    )


def test_the_cost_is_no_longer_quadratic():
    """Four times the work must not cost sixteen times the time."""

    small, _ = measure(tasks=100, repeats=1)
    large, _ = measure(tasks=400, repeats=1)
    ratio = large["seconds"] / small["seconds"]
    assert ratio < 8.0, (
        f"100 tasks cost {small['seconds']:.3f}s and 400 cost {large['seconds']:.3f}s "
        f"({ratio:.1f}x for 4x the work): the per-operation cost still grows with the store"
    )
