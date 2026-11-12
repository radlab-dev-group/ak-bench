"""The measured half: the same three schedules, against a pristine seed.

`hidden_tests/reference/tidewater/` is an untouched copy of the package as the
task ships it. The harness times the workspace and that copy with one script and
compares them, so the bar is a ratio and not a number that belongs to the
machine running the tests.
"""

from __future__ import annotations

import pytest

from bench_harness import MEASURED, candidate_and_reference

#: An optimisation has to buy at least a third of the CPU to count. The seed
#: spends four fifths of its time re-proving properties about state that did not
#: move, so a third is the floor of the argument, not a stretch.
CPU_TARGET = 0.65

#: Memory may move a little. Caching summaries and watch lists costs something,
#: and an optimisation that trades 2x the memory for 2x the speed has moved the
#: problem rather than solved it.
PEAK_TARGET = 1.35


def _ratios(schedule: str) -> tuple[float, float, dict, dict]:
    candidate, reference = candidate_and_reference(schedule)
    assert candidate["ok"], f"{schedule}: the optimised simulator reports {schedule} as unsafe"
    assert candidate["digest"] == reference["digest"], (
        f"{schedule}: the optimised run does not produce the reference trace; "
        "an optimisation may not move a byte of the output"
    )
    return candidate["cpu"] / reference["cpu"], candidate["peak"] / reference["peak"], candidate, reference


@pytest.mark.parametrize("schedule", MEASURED)
def test_the_cpu_cost_of_a_run_goes_down(schedule: str):
    cpu_ratio, _peak_ratio, candidate, reference = _ratios(schedule)
    assert cpu_ratio <= CPU_TARGET, (
        f"{schedule}: {candidate['cpu']:.2f}s against a baseline of {reference['cpu']:.2f}s "
        f"is {cpu_ratio:.0%} of it; the target is {CPU_TARGET:.0%}"
    )


@pytest.mark.parametrize("schedule", MEASURED)
def test_the_memory_cost_of_a_run_does_not_grow(schedule: str):
    _cpu_ratio, peak_ratio, candidate, reference = _ratios(schedule)
    assert peak_ratio <= PEAK_TARGET, (
        f"{schedule}: the optimised run peaks at {candidate['peak']} bytes against "
        f"{reference['peak']} for the baseline ({peak_ratio:.0%})"
    )


def test_the_workload_actually_ran():
    """A simulator that skips the work is fast and wrong; this says it was not."""

    candidate, reference = candidate_and_reference("baseline-steady")
    assert candidate["events"] == reference["events"], "the run produced a different number of events"
    assert candidate["events"] > 4000
