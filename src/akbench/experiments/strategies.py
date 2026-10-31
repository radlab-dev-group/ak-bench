"""Variant generation strategies (plan section 12.2).

The strategies are interchangeable functions over resolved factors. Every one of
them is deterministic: the same factors in the same order always produce the
same variants in the same order, because a variant list that moved between runs
would make a run's identity meaningless.

| Strategy | What it produces |
|---|---|
| ``full_factorial`` | the cross product of every factor |
| ``selected_factors`` | the cross product of the selected factors, the rest pinned |
| ``one_factor_at_a_time`` | the baseline plus one change per value |
| ``pairwise`` | a list that covers every pair of values |
| ``custom_matrix`` | exactly the combinations the experiment lists |
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from itertools import product
from typing import Any

from akbench.core.errors import AKBenchmarkError
from akbench.experiments.dimensions import Factor

Assignment = dict[str, Any]
Pair = tuple[int, Any, int, Any]


class StrategyError(AKBenchmarkError):
    """A strategy could not be applied to the given factors.

    ``code`` names the kind of problem, so the planner reports "the baseline is
    not part of this matrix" as itself rather than as an opaque strategy error.
    """

    code = "strategy_failed"


class BaselineValueError(StrategyError):
    """The baseline names a value this matrix cannot produce."""

    code = "baseline_value_invalid"


class BaselineMissingError(StrategyError):
    """A strategy that needs a reference configuration has none."""

    code = "baseline_missing"


def pinned_value(factor: Factor, baseline: dict[str, Any]) -> Any:
    """The value a factor keeps when it is not the one being varied.

    Order of preference: the experiment's baseline, the dimension's own default,
    the first declared value. All three are declared facts; none is invented.
    """
    if factor.id in baseline:
        return baseline[factor.id]
    declared = factor.descriptor.dimension.default
    if declared is not None:
        return declared
    return factor.values[0]


def _require_baseline_value(factor: Factor, baseline: dict[str, Any], strategy: str) -> None:
    if factor.id not in baseline:
        raise BaselineMissingError(
            f"strategy {strategy}: factor {factor.id!r} has no baseline value; every "
            "factor of a one-factor-at-a-time run needs one"
        )
    if not factor.accepts_value(baseline[factor.id]):
        raise BaselineValueError(
            f"strategy {strategy}: baseline value {baseline[factor.id]!r} for factor "
            f"{factor.id!r} is not one of the values this experiment varies "
            f"({list(factor.values)})"
        )


def _check_pinned(factors: Sequence[Factor], baseline: dict[str, Any], strategy: str) -> None:
    for factor in factors:
        value = pinned_value(factor, baseline)
        if not factor.accepts_value(value):
            raise StrategyError(
                f"strategy {strategy}: value {value!r} for factor {factor.id!r} is not "
                f"one of the declared values {list(factor.values)}"
            )


def full_factorial(
    factors: Sequence[Factor], baseline: dict[str, Any], selected: Sequence[str]
) -> list[Assignment]:
    """Every combination of every factor's values."""
    if not factors:
        return [{}]
    _check_pinned(factors, baseline, "full_factorial")
    combinations = product(*[list(factor.values) for factor in factors])
    return [
        {factor.id: value for factor, value in zip(factors, combo, strict=True)}
        for combo in combinations
    ]


def selected_factors(
    factors: Sequence[Factor], baseline: dict[str, Any], selected: Sequence[str]
) -> list[Assignment]:
    """Vary the selected factors and pin every other declared factor."""
    if not selected:
        raise StrategyError(
            "strategy selected_factors needs factors.selected: naming the factors "
            "that vary is the whole point of the strategy"
        )
    known = {factor.id for factor in factors}
    unknown = sorted(set(selected) - known)
    if unknown:
        raise StrategyError(
            f"strategy selected_factors names unknown factors: {', '.join(unknown)}"
        )
    varying = [factor for factor in factors if factor.id in set(selected)]
    pinned = [factor for factor in factors if factor.id not in set(selected)]
    _check_pinned(pinned, baseline, "selected_factors")

    assignments: list[Assignment] = []
    for combo in product(*[list(factor.values) for factor in varying]):
        assignment: Assignment = {factor.id: pinned_value(factor, baseline) for factor in pinned}
        assignment.update(
            {factor.id: value for factor, value in zip(varying, combo, strict=True)}
        )
        assignments.append(assignment)
    return assignments


def one_factor_at_a_time(
    factors: Sequence[Factor], baseline: dict[str, Any], selected: Sequence[str]
) -> list[Assignment]:
    """The baseline plus one changed factor value at a time.

    The baseline is the reference every other variant is measured against, so it
    must be the first variant and it must be exactly the baseline: a
    one-factor-at-a-time run built on some other reference would answer a
    different question than the one the experiment declares.
    """
    if not factors:
        return [{}]
    for factor in factors:
        _require_baseline_value(factor, baseline, "one_factor_at_a_time")
    base = {factor.id: baseline[factor.id] for factor in factors}

    assignments: list[Assignment] = [dict(base)]
    for factor in factors:
        for value in factor.values:
            if _same(value, base[factor.id]):
                continue
            assignment = dict(base)
            assignment[factor.id] = value
            assignments.append(assignment)
    return _deduplicate(assignments)


def pairwise(
    factors: Sequence[Factor], baseline: dict[str, Any], selected: Sequence[str]
) -> list[Assignment]:
    """A greedy covering array: every pair of values appears in some variant.

    Greedy rather than optimal on purpose. These experiments are tens of
    variants, and a deterministic greedy pass is easier to audit than a search
    whose result depends on luck.
    """
    if not factors:
        return [{}]
    _check_pinned(factors, baseline, "pairwise")
    if len(factors) == 1:
        return [{factors[0].id: value} for value in factors[0].values]

    pairs: list[Pair] = []
    for left in range(len(factors)):
        for right in range(left + 1, len(factors)):
            for first in factors[left].values:
                for second in factors[right].values:
                    pairs.append((left, first, right, second))

    uncovered: set[Pair] = set(pairs)
    assignments: list[Assignment] = []
    for pair in pairs:
        if pair not in uncovered:
            continue
        left, left_value, right, right_value = pair
        assignment: Assignment = {factors[left].id: left_value, factors[right].id: right_value}
        for index, factor in enumerate(factors):
            if index in (left, right):
                continue
            assignment[factor.id] = _value_covering_most(
                factor, index, assignment, factors, uncovered
            )
        assignments.append(assignment)
        uncovered -= _covered_pairs(assignment, factors)
    return _deduplicate(assignments)


def custom_matrix(
    factors: Sequence[Factor],
    baseline: dict[str, Any],
    selected: Sequence[str],
    combinations: Iterable[dict[str, Any]] | None = None,
) -> list[Assignment]:
    """Exactly the combinations the experiment declares, in that order."""
    if not combinations:
        raise StrategyError("strategy custom_matrix requires explicit combinations")
    known = {factor.id for factor in factors}
    assignments: list[Assignment] = []
    for position, combination in enumerate(combinations):
        unknown = sorted(set(combination) - known)
        if unknown:
            raise StrategyError(
                f"custom combination {position} names unknown factors: {', '.join(unknown)}"
            )
        assignment: Assignment = {}
        for factor in factors:
            if factor.id in combination:
                value = combination[factor.id]
                if not factor.accepts_value(value):
                    raise StrategyError(
                        f"custom combination {position}: value {value!r} for factor "
                        f"{factor.id!r} is not one of the declared values "
                        f"{list(factor.values)}"
                    )
            else:
                value = pinned_value(factor, baseline)
                if not factor.accepts_value(value):
                    raise StrategyError(
                        f"custom combination {position}: factor {factor.id!r} is not "
                        f"listed and its pinned value {value!r} is not allowed"
                    )
            assignment[factor.id] = value
        assignments.append(assignment)
    return _deduplicate(assignments)


def _value_covering_most(
    factor: Factor,
    index: int,
    assignment: Assignment,
    factors: Sequence[Factor],
    uncovered: set[Pair],
) -> Any:
    """The value covering the most still-uncovered pairs; ties keep declaration order."""
    fixed = [(other, value) for other, value in _assigned(factors, assignment) if other != index]
    best, best_count = factor.values[0], -1
    for value in factor.values:
        count = sum(
            _pair(other, other_value, index, value) in uncovered
            for other, other_value in fixed
        )
        if count > best_count:
            best, best_count = value, count
    return best


def _assigned(factors: Sequence[Factor], assignment: Assignment):
    for index, factor in enumerate(factors):
        if factor.id in assignment:
            yield index, assignment[factor.id]


def _pair(left_index: int, left_value: Any, right_index: int, right_value: Any) -> Pair:
    if left_index < right_index:
        return (left_index, left_value, right_index, right_value)
    return (right_index, right_value, left_index, left_value)


def _covered_pairs(assignment: Assignment, factors: Sequence[Factor]) -> set[Pair]:
    present = list(_assigned(factors, assignment))
    covered: set[Pair] = set()
    for position, (left_index, left_value) in enumerate(present):
        for right_index, right_value in present[position + 1 :]:
            covered.add(_pair(left_index, left_value, right_index, right_value))
    return covered


def _same(left: Any, right: Any) -> bool:
    """``True`` and ``1`` are different values here, so a boolean factor cannot
    collapse into an integer one."""
    return type(left) is type(right) and left == right


def _canonical(assignment: dict[str, Any]) -> str:
    return json.dumps(assignment, sort_keys=True, default=repr)


def _deduplicate(assignments: Sequence[Assignment]) -> list[Assignment]:
    seen: set[str] = set()
    unique: list[Assignment] = []
    for assignment in assignments:
        key = _canonical(assignment)
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(assignment))
    return unique


STRATEGIES: dict[str, Callable[..., list[Assignment]]] = {
    "full_factorial": full_factorial,
    "selected_factors": selected_factors,
    "one_factor_at_a_time": one_factor_at_a_time,
    "pairwise": pairwise,
    "custom_matrix": custom_matrix,
}


def strategy_for(name: str) -> Callable[..., list[Assignment]]:
    try:
        return STRATEGIES[name]
    except KeyError as exc:
        known = ", ".join(sorted(STRATEGIES))
        raise StrategyError(f"unknown matrix strategy {name!r}; known strategies: {known}") from exc
