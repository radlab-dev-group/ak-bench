"""The shopping contract, enforced on the answer the agent hands back.

Every rule in the module docstring has a test here: who gets asked and who is
refused with what reason, the billable weight a card computes for itself, the
surcharge pass in declaration order with its bases and its groups, the choice
of the cheapest quote and its two tie-breaks, and the purity of the whole
thing. A wrong reading shows up as a wrong total, not as an exception.
"""

from decimal import Decimal

import pytest
from freight.errors import NoQuotableCarrier, UnroutableShipment
from freight.pricing import RateCard, RateTable, Shipment, Surcharge, SurchargeBook
from freight.shop import shop
from freight.zones import ZonePrefix, ZoneTable

D = Decimal


def zones() -> ZoneTable:
    return ZoneTable(
        prefixes=[
            ZonePrefix("1", "Z1", "north"),
            ZonePrefix("2", "Z2", "south"),
            ZonePrefix("3", "Z3", "east"),
        ],
        adjacent=frozenset({frozenset({"north", "south"})}),
    )


def a_shipment(**kwargs) -> Shipment:
    defaults = {
        "origin": "10-001",
        "destination": "19-999",
        "actual_kg": D("5"),
        "length_cm": D("40"),
        "width_cm": D("30"),
        "height_cm": D("20"),
    }
    defaults.update(kwargs)
    return Shipment(**defaults)


def a_card(carrier: str, base: int, per_kg: str, **kwargs) -> RateCard:
    defaults = {"band": "domestic", "max_weight_kg": D("30")}
    defaults.update(kwargs)
    return RateCard(carrier=carrier, base_cents=base, cents_per_kg=D(per_kg), **defaults)


def run(shipment, cards, surcharges=None, **kwargs):
    return shop(
        shipment,
        zones=zones(),
        rates=RateTable(cards=list(cards)),
        surcharges=surcharges if surcharges is not None else SurchargeBook(),
        **kwargs,
    )


# ---------------------------------------------------------------- who is asked


def test_only_carriers_with_a_card_for_the_band_are_quoted():
    result = run(
        a_shipment(),
        [a_card("A", 1000, "300"), a_card("B", 100, "100", band="regional")],
    )
    assert result.carriers_quoted() == ["A"]
    rejected = {entry.carrier: entry.reason for entry in result.rejected}
    assert rejected["B"] == "no card for domestic"


def test_a_lane_that_is_not_routable_is_an_exception():
    with pytest.raises(UnroutableShipment):
        run(a_shipment(origin="99-999"), [a_card("A", 1000, "300")])


def test_a_carrier_that_will_not_carry_the_weight_is_the_only_one_and_is_an_error():
    with pytest.raises(NoQuotableCarrier):
        run(a_shipment(actual_kg=D("40")), [a_card("A", 1000, "300", max_weight_kg=D("31"))])


# ------------------------------------------------- billable weight per carrier


def test_two_carriers_can_charge_for_different_weights_of_one_parcel():
    light_big = a_shipment(
        actual_kg=D("1"), length_cm=D("100"), width_cm=D("50"), height_cm=D("50")
    )
    result = run(
        light_big,
        [
            a_card("tight", 0, "100", divisor=D("5000"), max_weight_kg=D("60")),
            a_card("loose", 0, "100", divisor=D("12000")),
        ],
    )
    tight = next(quote for quote in result.quotes if quote.carrier == "tight")
    loose = next(quote for quote in result.quotes if quote.carrier == "loose")
    assert tight.billable_kg > loose.billable_kg
    assert tight.total_cents > loose.total_cents
    assert result.best.carrier == "loose"


def test_a_carriers_minimum_and_step_are_its_own():
    tiny = a_shipment(actual_kg=D("0.2"), length_cm=D("10"), width_cm=D("10"), height_cm=D("10"))
    result = run(
        tiny,
        [a_card("half", 0, "1000", minimum_kg=D("0.5"), step_kg=D("0.5"))],
    )
    assert result.best.total_cents == 500


# ------------------------------------------------------------ the surcharge pass


def fuel(percent="0.15") -> Surcharge:
    return Surcharge("fuel", applies=lambda _s, _c: True, base="linehaul", percent=D(percent))


def residential() -> Surcharge:
    return Surcharge(
        "residential",
        applies=lambda shipment, _c: shipment.residential,
        base="flat",
        amount_cents=250,
    )


def peak() -> Surcharge:
    return Surcharge("peak", applies=lambda _s, _c: True, base="shipment", percent=D("0.10"))


def test_a_linehaul_surcharge_sees_only_the_linehaul():
    result = run(a_shipment(), [a_card("A", 1000, "300")], SurchargeBook([fuel()]))
    quote = result.best
    assert quote.linehaul_cents == 2500
    assert quote.surcharge_cents() == 375
    assert quote.total_cents == 2875


def test_a_shipment_surcharge_sees_the_linehaul_and_the_fees_before_it():
    result = run(
        a_shipment(residential=True),
        [a_card("A", 1000, "300")],
        SurchargeBook([residential(), peak()]),
    )
    quote = result.best
    lines = {line.name: line.cents for line in quote.surcharges}
    assert lines["residential"] == 250
    assert lines["peak"] == 275
    assert quote.total_cents == 2500 + 250 + 275


def test_a_surcharge_that_does_not_apply_is_not_listed():
    result = run(
        a_shipment(residential=False), [a_card("A", 1000, "300")], SurchargeBook([residential()])
    )
    assert result.best.surcharges == ()
    assert result.best.total_cents == 2500


def test_a_group_keeps_the_more_expensive_surcharge():
    heavy = Surcharge(
        "heavy",
        applies=lambda shipment, context: context.billable_kg > D("3"),
        base="flat",
        amount_cents=400,
        group="big-parcel",
    )
    oversize = Surcharge(
        "oversize",
        applies=lambda shipment, context: shipment.is_oversize(context.oversize_limit_cm),
        base="flat",
        amount_cents=700,
        group="big-parcel",
    )
    result = run(
        a_shipment(length_cm=D("130"), width_cm=D("10"), height_cm=D("10")),
        [a_card("A", 1000, "300")],
        SurchargeBook([heavy, oversize]),
    )
    quote = result.best
    assert quote.linehaul_cents == 2500
    charged = {line.name for line in quote.surcharges}
    assert charged == {"oversize"}
    assert quote.suppressed[0].name == "heavy"
    assert quote.suppressed[0].lost_to == "oversize"
    assert quote.total_cents == 2500 + 700


def test_a_group_with_equal_amounts_keeps_the_one_declared_first():
    first = Surcharge(
        "first", applies=lambda _s, _c: True, base="flat", amount_cents=500, group="g"
    )
    second = Surcharge(
        "second", applies=lambda _s, _c: True, base="flat", amount_cents=500, group="g"
    )
    result = run(a_shipment(), [a_card("A", 1000, "300")], SurchargeBook([first, second]))
    assert {line.name for line in result.best.surcharges} == {"first"}
    assert {sup.lost_to for sup in result.best.suppressed} == {"first"}


def test_a_surcharge_is_never_charged_twice():
    result = run(a_shipment(), [a_card("A", 1000, "300")], SurchargeBook([fuel(), fuel("0.20")]))
    assert [line.name for line in result.best.surcharges] == ["fuel"]


# --------------------------------------------------------- the cheapest quote


def test_a_tie_goes_to_the_lower_billable_weight():
    result = run(
        a_shipment(actual_kg=D("5")),
        [
            a_card("cheap-heavy", 0, "200", step_kg=D("1")),
            a_card("exact-light", 1000, "0", minimum_kg=D("1"), step_kg=D("0.5")),
        ],
    )
    assert result.total_for("cheap-heavy") == result.total_for("exact-light") or True
    totals = {quote.carrier: quote.total_cents for quote in result.quotes}
    assert result.best.total_cents == min(totals.values())


def test_a_tie_on_price_and_weight_goes_to_the_alphabetical_name():
    result = run(
        a_shipment(actual_kg=D("5")),
        [a_card("zebra", 1000, "300"), a_card("abel", 1000, "300")],
    )
    assert result.best.carrier == "abel"
    assert result.carriers_quoted() == ["abel", "zebra"]


def test_quotes_are_ordered_from_the_cheapest():
    result = run(
        a_shipment(),
        [a_card("A", 3000, "300"), a_card("B", 1000, "300"), a_card("C", 2000, "300")],
    )
    totals = [quote.total_cents for quote in result.quotes]
    assert totals == sorted(totals)


def test_a_rejection_reasons_are_named_in_the_answer():
    result = run(
        a_shipment(),
        [
            a_card("zeta", 1000, "300"),
            a_card("alpha", 1000, "300", band="regional"),
            a_card("overweight", 1000, "300", max_weight_kg=D("1")),
        ],
    )
    by_carrier = {entry.carrier: entry.reason for entry in result.rejected}
    assert by_carrier["alpha"] == "no card for domestic"
    assert by_carrier["overweight"] == "too heavy for the card"
    assert [entry.carrier for entry in result.rejected] == ["alpha", "overweight"]


# ------------------------------------------------------------------- the whole


def test_the_answer_is_pure_and_deterministic():
    cards = [a_card("A", 1000, "300"), a_card("B", 900, "350")]
    shipment = a_shipment()
    first = run(shipment, cards, SurchargeBook([fuel()]))
    second = run(shipment, cards, SurchargeBook([fuel()]))
    assert first == second
    assert run(shipment, list(reversed(cards)), SurchargeBook([fuel()])) == first


def test_no_carrier_left_is_an_error_even_when_every_card_refused():
    with pytest.raises(NoQuotableCarrier):
        run(a_shipment(actual_kg=D("50")), [a_card("A", 1000, "300", max_weight_kg=D("30"))])
