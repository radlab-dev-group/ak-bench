"""What a developer can check without the hidden cases: the shape of an answer."""

from decimal import Decimal

import pytest
from freight.errors import NoQuotableCarrier
from freight.pricing import RateCard, RateTable, Shipment, SurchargeBook
from freight.shop import ShoppingResult, shop
from freight.zones import ZonePrefix, ZoneTable

D = Decimal


def zones() -> ZoneTable:
    return ZoneTable(
        prefixes=[
            ZonePrefix("1", "Z1", "north"),
            ZonePrefix("2", "Z2", "south"),
        ],
        adjacent=frozenset({frozenset({"north", "south"})}),
    )


def rates(*cards: RateCard) -> RateTable:
    return RateTable(cards=list(cards))


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


def test_a_single_carrier_is_the_best_one():
    result = shop(
        a_shipment(),
        zones=zones(),
        rates=rates(a_card("A", 1000, "300")),
        surcharges=SurchargeBook(),
    )
    assert isinstance(result, ShoppingResult)
    assert result.best.carrier == "A"
    assert result.best.total_cents == 1000 + 5 * 300


def test_the_cheapest_carrier_is_the_best_one():
    result = shop(
        a_shipment(),
        zones=zones(),
        rates=rates(a_card("A", 1000, "300"), a_card("B", 900, "200")),
        surcharges=SurchargeBook(),
    )
    assert result.best.carrier == "B"
    assert result.carriers_quoted() == ["B", "A"]


def test_a_carrier_with_no_card_for_the_band_is_not_the_answer():
    with pytest.raises(NoQuotableCarrier):
        shop(
            a_shipment(origin="10-001", destination="20-001"),
            zones=zones(),
            rates=rates(a_card("A", 1000, "300")),
            surcharges=SurchargeBook(),
        )


def test_no_price_at_all_is_an_error_not_an_empty_answer():
    with pytest.raises(NoQuotableCarrier):
        shop(
            a_shipment(),
            zones=zones(),
            rates=rates(),
            surcharges=SurchargeBook(),
        )
