"""A line-haul is base plus per-kilogram, rounded once, and a card refuses the too-heavy."""

from decimal import Decimal

import pytest
from freight.pricing import RateCard, RateTable, Shipment, Surcharge, round_cents

D = Decimal


def a_card(**kwargs) -> RateCard:
    defaults = {
        "carrier": "A",
        "band": "domestic",
        "base_cents": 1000,
        "cents_per_kg": D("300"),
        "max_weight_kg": D("30"),
    }
    defaults.update(kwargs)
    return RateCard(**defaults)


def a_shipment(**kwargs) -> Shipment:
    defaults = {
        "origin": "10-001",
        "destination": "10-002",
        "actual_kg": D("5"),
        "length_cm": D("40"),
        "width_cm": D("30"),
        "height_cm": D("20"),
    }
    defaults.update(kwargs)
    return Shipment(**defaults)


def test_a_line_haul_is_base_plus_per_kilo():
    assert a_card().linehaul_cents(D("2")) == 1000 + 600


def test_a_line_haul_rounds_half_away_from_zero():
    assert a_card(cents_per_kg=D("250.5")).linehaul_cents(D("1")) == 1251
    assert a_card(cents_per_kg=D("250.4")).linehaul_cents(D("1")) == 1250
    assert a_card(cents_per_kg=D("249.4")).linehaul_cents(D("1")) == 1249


def test_a_minimum_charge_wins_when_the_formula_is_cheaper():
    cheap = a_card(base_cents=0, cents_per_kg=D("1"), minimum_charge_cents=500)
    assert cheap.linehaul_cents(D("0.5")) == 500


def test_a_card_carries_up_to_its_maximum_and_not_one_gram_more():
    assert a_card().carries(D("30"))
    assert not a_card().carries(D("30.1"))


def test_a_card_prices_a_shipment_with_its_own_divisor():
    light = a_shipment(actual_kg=D("1"), length_cm=D("100"), width_cm=D("50"), height_cm=D("50"))
    assert a_card(divisor=D("5000"), step_kg=D("0.5")).billable_for(light).charged == D("50")
    assert a_card(divisor=D("12000"), step_kg=D("0.5")).billable_for(light).charged == D("21")


def test_the_table_finds_the_card_for_a_lane():
    table = RateTable(cards=[a_card(), a_card(carrier="B", band="regional")])
    assert table.card_for("B", "regional").carrier == "B"
    assert table.card_for("B", "domestic") is None


def test_a_percentage_surcharge_is_computed_on_the_line_haul():
    surcharge = Surcharge("fuel", applies=lambda _s, _c: True, base="linehaul", percent=D("0.15"))
    context = _context(linehaul_cents=1000, fixed_fees_cents=200)
    assert surcharge.amount_for(context) == 150


def test_a_shipment_percentage_surcharge_sees_the_fees_too():
    surcharge = Surcharge("peak", applies=lambda _s, _c: True, base="shipment", percent=D("0.10"))
    context = _context(linehaul_cents=1000, fixed_fees_cents=200)
    assert surcharge.amount_for(context) == 120


def test_a_flat_surcharge_sees_nothing():
    surcharge = Surcharge("residential", applies=lambda _s, _c: True, base="flat", amount_cents=250)
    context = _context(linehaul_cents=1000, fixed_fees_cents=0)
    assert surcharge.amount_for(context) == 250


def test_a_flat_surcharge_cannot_carry_a_percent():
    with pytest.raises(ValueError):
        Surcharge("bad", applies=lambda _s, _c: True, base="flat", percent=D("0.1"))


def test_round_cents_is_the_single_rounding_rule():
    assert round_cents(D("10.5")) == 11
    assert round_cents(D("-10.5")) == -11


def _context(linehaul_cents: int, fixed_fees_cents: int):
    from freight.pricing import Context

    return Context(
        billable_kg=D("5"),
        linehaul_cents=linehaul_cents,
        fixed_fees_cents=fixed_fees_cents,
        oversize_limit_cm=D("120"),
    )
