"""The CDCL engine: propagation, learning, jumping, and the version encoding.

The solver is the part of the package whose behaviour is defined by its
intermediate structure as much as by its answer: two runs must agree on the
trail, not only on the model. These tests therefore pin both halves — the
answer on problems with a known answer, and the shape of the search on
problems small enough to write down.
"""

import itertools

import pytest
from depweaver.solver import Activities, Solver, Trail, Watchers, encode, resolve


def satisfies(model, clauses):
    return all(
        any(model[abs(literal)] if literal > 0 else not model[abs(literal)] for literal in clause)
        for clause in clauses
    )


def brute(clauses, variables):
    for bits in itertools.product((False, True), repeat=variables):
        model = {index + 1: bits[index] for index in range(variables)}
        if satisfies(model, clauses):
            return model
    return None


# --------------------------------------------------------------------------
# the trail


def test_a_rollback_undoes_everything_above_the_level_it_names():
    trail = Trail()
    trail.assign(1, 0)
    trail.assign(2, 1)
    trail.assign(3, 2)
    undone = trail.rollback(1)
    # Only the assignments above level 1 come off; the one at level 1 stays,
    # because a backjump to a level lands *on* it.
    assert undone == [3]
    assert trail.value(2) is True
    assert trail.value(3) is None
    trail.rollback(0)
    assert trail.level == 0
    assert trail.value(1) is True
    assert trail.value(2) is None


def test_a_variable_assigned_twice_is_the_bug_the_trail_refuses():
    trail = Trail()
    trail.assign(4, 1)
    with pytest.raises(ValueError, match="already assigned"):
        trail.assign(-4, 2)


def test_only_the_literate_part_of_the_trail_is_a_decision():
    trail = Trail()
    trail.assign(1, 1)
    trail.assign(2, 1, (2, -1))
    assert trail.decisions() == [(1, 1)]


# ---------------------------------------------------------------------------
# the watchers


def test_a_clause_is_found_under_either_of_its_watches():
    watchers = Watchers()
    watchers.watch(3, 11)
    watchers.watch(-3, 11)
    assert watchers.watching(3) == [11]
    assert watchers.take(3) == [11]
    assert watchers.watching(3) == []
    assert watchers.watching(-3) == [11]


# ---------------------------------------------------------------------------
# the heuristic


def test_activity_decides_and_a_tie_breaks_by_variable_number():
    activities = Activities()
    activities.bump([2, 5])
    assert activities.decide([2, 5, 7]) == 5
    activities.bump([7])
    assert activities.decide([2, 5, 7]) == 7
    # Nothing bumped: the highest number wins, not the first offered.
    assert Activities().decide([4, 9, 2]) == 9


def test_the_decay_factor_is_a_probability_and_says_so():
    for bad in (0.0, 1.0, -0.5, 2.0):
        with pytest.raises(ValueError):
            Activities(decay=bad)


# ---------------------------------------------------------------------------
# solving


def test_a_contradiction_between_two_units_is_caught_before_the_search():
    solver = Solver([(1,), (-1,)], variables=1)
    assert solver.solve() is False
    assert solver.conflicts == 0
    assert solver.refuted is True


def test_a_clause_already_true_on_the_trail_is_still_satisfiable():
    solver = Solver([(1, 2), (-2, 3)], variables=3)
    assert solver.solve() is True
    assert satisfies(solver.model(), solver.clauses)


def test_an_empty_clause_makes_the_problem_unsolvable():
    assert Solver([(1, 2), ()], variables=2).solve() is False


@pytest.mark.parametrize(
    "clauses, variables",
    [
        (((1, 2), (-1, 2), (1, -2)), 2),
        (((1,), (-1, 2), (-2, 3)), 3),
        (((1, 2, 3), (-1, -2), (-2, -3), (-3, -1)), 3),
        (((-1, -2, -3), (1, 2), (2, 3), (1, 3)), 3),
        (((1, 2), (3, 4), (-2, -3), (-1, -4)), 4),
        ((), 0),
    ],
)
def test_the_solver_and_the_brute_force_agree(clauses, variables):
    solver = Solver(clauses, variables=variables)
    answer = solver.solve()
    model = brute(clauses, variables)
    assert answer is (model is not None)
    if answer:
        assert satisfies(solver.model(), clauses)


def test_a_small_family_of_random_instances_agrees_with_brute_force():
    # A fixed linear congruential generator: no dependency on Python's random
    # ordering, and the same 40 instances on every machine.
    state = 20261112
    for _ in range(40):
        variables = (state := (state * 1103515245 + 12345) % 2**31) % 5 + 2
        count = state % 8 + 2
        clauses = []
        for _ in range(count):
            state = (state * 1103515245 + 12345) % 2**31
            width = state % 3 + 1
            literals = []
            for _ in range(width):
                state = (state * 1103515245 + 12345) % 2**31
                literal = state % variables + 1
                literals.append(literal if state % 2 == 0 else -literal)
            clauses.append(tuple(dict.fromkeys(literals)))
        solver = Solver(clauses, variables=variables)
        answer = solver.solve()
        assert answer is (brute(clauses, variables) is not None)
        if answer:
            assert satisfies(solver.model(), clauses)


def test_two_runs_of_the_same_problem_do_the_same_things_in_the_same_order():
    clauses = ((1, 2, 3), (-1, 4), (-2, 4), (-3, -4), (5, -1), (-5, 2))
    first, second = Solver(clauses, variables=5), Solver(clauses, variables=5)
    assert first.solve() == second.solve()
    assert first.trace() == second.trace()
    assert first.conflicts == second.conflicts
    assert first.decisions == second.decisions


def test_learning_is_not_cheating_and_the_model_still_satisfies_the_input():
    # Learning changes the search, not the answer: a model of a solver that
    # learned clauses is still a model of the clauses it was given, because
    # every learned clause is a consequence of the conflict that made it.
    clauses = [(1, 2), (-1, 3), (-2, 3), (3, 4), (-4, -3, -1), (2, 4)]
    solver = Solver(clauses, variables=4)
    assert solver.solve() is True
    assert satisfies(solver.model(), clauses)
    for learned in solver.learnings():
        assert satisfies(solver.model(), (learned,))


def test_the_input_clauses_survive_the_search_them():
    clauses = [(1, 2), (-1, 3), (-2, 3), (-3, 4), (-4, -1, -3)]
    solver = Solver(clauses, variables=4)
    assert solver.solve() is True
    # The search rewrites the literal order of a clause while it maintains its
    # watches, so the input is compared up to permutation: the content of the
    # problem must be untouched, and it is.
    stored = [frozenset(clause) for clause in solver.clauses[: solver.input_count]]
    original = [frozenset(clause) for clause in clauses]
    assert stored == original
    assert solver.learned_count == len(solver.learnings())


def test_a_budget_is_a_termination_promise_not_a_answer():
    hard = [(1, 2, 3), (-1, -2), (-1, -3), (-2, -3), (4, 5, 6), (-4, -5), (-4, -6), (-5, -6)]
    solver = Solver(hard, variables=6)
    with pytest.raises(RecursionError):
        solver.solve(budget=0)


# ---------------------------------------------------------------------------
# the encoding of the version problem


PACKAGES = {
    "app": [("1.0.0", False), ("1.1.0", False)],
    "core": [("1.0.0", False), ("2.0.0", False), ("3.0.0", False)],
    "util": [("0.9.0", False), ("1.0.0", False), ("1.1.0", False)],
}


def test_variables_are_numbered_in_package_order_not_in_input_order():
    clauses, maps, count = encode(PACKAGES, [("app", ["1.1.0"])])
    ordered = sorted(maps["pick"].items(), key=lambda item: item[1])
    assert [name for (name, _), _ in ordered[:2]] == ["app", "app"]
    assert count == 2 * sum(len(rows) for rows in PACKAGES.values())
    assert clauses


def test_a_requirement_no_version_satisfies_is_the_empty_clause():
    _clauses, _maps, count = encode(PACKAGES, [("core", [])])
    solver = Solver(*encode(PACKAGES, [("core", [])])[:1], variables=count)
    assert solver.solve() is False


def test_two_versions_of_one_package_cannot_both_be_picked():
    clauses, maps, count = encode(PACKAGES, [("core", ["1.0.0", "2.0.0", "3.0.0"])])
    solver = Solver(clauses, variables=count)
    assert solver.solve() is True
    model = solver.model()
    picked = [key for key, var in maps["pick"].items() if model.get(var)]
    assert sum(1 for name, _ in picked if name == "core") == 1


def test_resolve_prefers_the_highest_version_that_still_works():
    answer = resolve(PACKAGES, [("app", ["1.0.0", "1.1.0"]), ("core", ["1.0.0", "2.0.0"])])
    assert answer == {"app": "1.1.0", "core": "2.0.0", "util": "1.1.0"}


def test_resolve_reports_nothing_when_the_requirements_cannot_be_met():
    assert resolve(PACKAGES, [("app", ["1.0.0"]), ("core", [])]) is None


def test_resolve_is_a_function_of_its_input():
    requirements = [("app", ["1.0.0", "1.1.0"]), ("util", ["0.9.0", "1.0.0"])]
    assert resolve(PACKAGES, requirements) == resolve(PACKAGES, requirements)
