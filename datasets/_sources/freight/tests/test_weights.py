"""Billable weight: the greater of two weights, rounded up once, at the end."""

from decimal import Decimal

import pytest
from freight.weights import billable_weight, round_up_to_step, volumetric_weight

D = Decimal


def test_the_volumetric_weight_of_a_box_is_its_volume_over_the_divisor():
    assert volumetric_weight(D("50"), D("40"), D("30"), D("5000")) == D("12")


def test_a_heavy_small_parcel_is_charged_its_actual_weight():
    answer = billable_weight(
        D("20"), D("30"), D("20"), D("10"), divisor=D("5000"), minimum_kg=D("0.5"), step_kg=D("0.5")
    )
    assert answer.basis == "actual"
    assert answer.charged == D("20")


def test_a_light_big_parcel_is_charged_its_volumetric_weight():
    answer = billable_weight(
        D("1"), D("100"), D("50"), D("50"), divisor=D("5000"), minimum_kg=D("0.5"), step_kg=D("0.5")
    )
    assert answer.basis == "volumetric"
    assert answer.charged == D("50")


def test_the_minimum_is_applied_before_the_step():
    answer = billable_weight(
        D("0.1"), D("10"), D("10"), D("10"), divisor=D("5000"), minimum_kg=D("2"), step_kg=D("0.5")
    )
    assert answer.basis == "minimum"
    assert answer.charged == D("2")


def test_a_weight_on_the_step_does_not_climb():
    assert round_up_to_step(D("3"), D("0.5")) == D("3")


def test_a_weight_just_past_the_step_climbs_one_step():
    assert round_up_to_step(D("3.01"), D("0.5")) == D("3.5")


def test_a_nonpositive_weight_never_bills():
    assert round_up_to_step(D("0"), D("0.5")) == D("0")


def test_a_zero_divisor_is_refused():
    with pytest.raises(ValueError):
        volumetric_weight(D("10"), D("10"), D("10"), D("0"))
