"""The search path is the behaviour, so the behaviour is recorded.

Twenty dependency graphs and ten encodings, captured from the engine as it
stands today: the lockfile it produces, the trail it took line by line, and the
counters the search leaves behind. A refactor that reorders a scan changes the
trail and is caught here even when the answer still reads satisfiable.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

GOLDENS = Path(__file__).resolve().parent / "goldens" / "determinism.json"


def _goldens() -> dict:
    return json.loads(GOLDENS.read_text(encoding="utf-8"))


def _graph(seed: int):
    """The same function of the same seed the goldens were recorded from."""

    rng = random.Random(seed)
    names = [f"pkg{i}" for i in range(rng.randint(3, 6))]
    packages = {}
    for name in names:
        versions = sorted(
            {
                f"{rng.randint(0, 3)}.{rng.randint(0, 9)}.{rng.randint(0, 3)}"
                for _ in range(rng.randint(1, 4))
            }
        )
        packages[name] = [(version, rng.random() < 0.2) for version in versions]
    requirements = []
    for name in names:
        for _ in range(rng.randint(0, 2)):
            eligible = [v for v, pre in packages[name] if not pre or rng.random() < 0.5]
            if eligible:
                requirements.append((name, eligible))
    return packages, requirements


def test_resolve_returns_the_same_lockfile_for_twenty_graphs():
    from depweaver.solver import resolve

    for case in _goldens()["resolve"]:
        packages, requirements = _graph(case["seed"])
        assert resolve(packages, requirements) == case["answer"], (
            f"seed {case['seed']}: the lockfile changed"
        )


@pytest.mark.parametrize("seed", [100 + index for index in range(10)])
def test_the_solver_takes_the_recorded_path(seed: int):
    from depweaver.solver import Solver, encode

    case = next(item for item in _goldens()["traces"] if item["seed"] == seed)
    clauses, _maps, count = encode(*_graph(seed))
    solver = Solver(clauses, variables=count)

    assert solver.solve() is case["satisfiable"], f"seed {seed}: the answer changed"
    assert solver.trace() == case["trace"], (
        f"seed {seed}: the search took a different path "
        f"({len(solver.trace())} trail lines against the recorded {len(case['trace'])})"
    )
    for counter in ("conflicts", "decisions", "propagations", "learned_count"):
        assert getattr(solver, counter) == case[counter], (
            f"seed {seed}: {counter} is {getattr(solver, counter)}, was {case[counter]}"
        )
    assert [list(clause) for clause in solver.learnings()] == case["learnings"], (
        f"seed {seed}: the learned clauses changed"
    )
    assert {str(key): value for key, value in solver.model().items()} == case["model"], (
        f"seed {seed}: the model changed"
    )


def test_two_runs_of_the_same_graph_in_one_process_are_identical():
    from depweaver.solver import Solver, encode

    packages, requirements = _graph(7)
    clauses, _maps, count = encode(packages, requirements)

    first = Solver(clauses, variables=count)
    first.solve()
    second = Solver(clauses, variables=count)
    second.solve()

    assert first.trace() == second.trace()
    assert first.model() == second.model()
