"""Matrix strategies (plan section 12.2): sizes, coverage and determinism.

The strategies decide what an experiment costs, so their counts are tested as
facts rather than as properties of one implementation: a full factorial of 2x3
is six variants, one-factor-at-a-time of the same matrix is the reference plus
one change per value, and pairwise covers every pair.
"""

from __future__ import annotations

import pytest

from akbench.descriptors import DimensionDescriptor
from akbench.experiments.dimensions import Factor
from akbench.experiments.strategies import (
    StrategyError,
    custom_matrix,
    full_factorial,
    one_factor_at_a_time,
    pairwise,
    selected_factors,
    strategy_for,
)


def factor(dimension_id: str, values: list[object], **body: object) -> Factor:
    descriptor = DimensionDescriptor(
        id=dimension_id,
        version="1.0.0",
        dimension={"type": "categorical", "controllable": True, "values": values, **body},
    )
    return Factor(id=dimension_id, descriptor=descriptor, values=tuple(values))


KNOWLEDGE = lambda: factor("knowledge_enabled", [False, True])  # noqa: E731
MODEL = lambda: factor("model", ["a", "b", "c"])  # noqa: E731


def test_full_factorial_is_the_cross_product() -> None:
    variants = full_factorial([KNOWLEDGE(), MODEL()], {}, [])

    assert len(variants) == 6
    assert {(v["knowledge_enabled"], v["model"]) for v in variants} == {
        (flag, model) for flag in (False, True) for model in ("a", "b", "c")
    }


def test_full_factorial_is_deterministic() -> None:
    factors = [KNOWLEDGE(), MODEL()]
    assert full_factorial(factors, {}, []) == full_factorial(factors, {}, [])


def test_full_factorial_without_factors_is_a_single_reference_variant() -> None:
    assert full_factorial([], {}, []) == [{}]


def test_one_factor_at_a_time_changes_one_axis_at_a_time() -> None:
    baseline = {"knowledge_enabled": False, "model": "a"}

    variants = one_factor_at_a_time([KNOWLEDGE(), MODEL()], baseline, [])

    assert variants[0] == baseline, "the reference configuration comes first"
    assert len(variants) == 1 + 1 + 2, "one change of knowledge, two further models"
    for variant in variants[1:]:
        changed = [key for key in baseline if variant[key] != baseline[key]]
        assert len(changed) == 1


def test_pairwise_covers_every_pair_of_values() -> None:
    factors = [
        factor("knowledge_enabled", [False, True]),
        factor("model", ["a", "b", "c"]),
        factor("routing", [False, True]),
    ]

    variants = pairwise(factors, {}, [])

    pairs: set[tuple[str, object, str, object]] = set()
    for left in range(len(factors)):
        for right in range(left + 1, len(factors)):
            for a in factors[left].values:
                for b in factors[right].values:
                    pairs.add((factors[left].id, a, factors[right].id, b))
    covered: set[tuple[str, object, str, object]] = set()
    for variant in variants:
        keys = list(variant)
        for i, left in enumerate(keys):
            for right in keys[i + 1 :]:
                covered.add((left, variant[left], right, variant[right]))
                covered.add((right, variant[right], left, variant[left]))
    assert pairs <= covered
    assert len(variants) < 12, "pairwise must be smaller than the full factorial"


def test_pairwise_of_one_factor_lists_its_values() -> None:
    assert pairwise([KNOWLEDGE()], {}, []) == [
        {"knowledge_enabled": False},
        {"knowledge_enabled": True},
    ]


def test_selected_factors_vary_only_the_named_dimensions() -> None:
    factors = [KNOWLEDGE(), MODEL()]
    baseline = {"knowledge_enabled": False, "model": "b"}

    variants = selected_factors(factors, baseline, ["model"])

    assert {v["knowledge_enabled"] for v in variants} == {False}, "pinned by the baseline"
    assert {v["model"] for v in variants} == {"a", "b", "c"}


def test_selected_factors_rejects_unknown_names() -> None:
    with pytest.raises(StrategyError, match="unknown factors"):
        selected_factors([KNOWLEDGE()], {}, ["nope"])


def test_custom_matrix_uses_the_declared_rows() -> None:
    combinations = [
        {"knowledge_enabled": False, "model": "a"},
        {"knowledge_enabled": True, "model": "c"},
    ]

    variants = custom_matrix([KNOWLEDGE(), MODEL()], {}, [], combinations=combinations)

    assert variants == combinations


def test_custom_matrix_rejects_undeclared_values() -> None:
    with pytest.raises(StrategyError, match="is not one of the declared values"):
        custom_matrix(
            [KNOWLEDGE()],
            {},
            [],
            combinations=[{"knowledge_enabled": "sometimes"}],
        )


def test_custom_matrix_needs_its_combinations() -> None:
    with pytest.raises(StrategyError, match="requires explicit combinations"):
        custom_matrix([KNOWLEDGE()], {}, [])


def test_a_baseline_outside_the_value_space_is_refused() -> None:
    from akbench.experiments.strategies import BaselineValueError

    with pytest.raises(BaselineValueError, match="is not one of the values this experiment varies"):
        one_factor_at_a_time([KNOWLEDGE()], {"knowledge_enabled": "maybe"}, [])


def test_a_baseline_missing_for_a_factor_is_named() -> None:
    from akbench.experiments.strategies import BaselineMissingError

    with pytest.raises(BaselineMissingError, match="has no baseline value"):
        one_factor_at_a_time([KNOWLEDGE()], {}, [])


def test_strategy_lookup_names_what_it_does_not_know() -> None:
    with pytest.raises(StrategyError, match="unknown matrix strategy"):
        strategy_for("simulated_annealing")


def test_every_declared_strategy_is_reachable() -> None:
    from akbench.experiments.descriptor import MatrixStrategy

    for strategy in MatrixStrategy:
        assert strategy_for(strategy.value) is not None
