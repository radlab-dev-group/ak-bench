"""The longest prefix wins, and two regions decide the band."""

import pytest
from freight.errors import AmbiguousPrefixes, UnroutableShipment
from freight.zones import DOMESTIC, LONG_HAUL, REGIONAL, ZonePrefix, ZoneTable

NORTH = "north"
SOUTH = "south"
EAST = "east"


def a_table() -> ZoneTable:
    return ZoneTable(
        prefixes=[
            ZonePrefix("1", "Z1", NORTH),
            ZonePrefix("12-3", "Z12", NORTH),
            ZonePrefix("2", "Z2", SOUTH),
            ZonePrefix("3", "Z3", EAST),
        ],
        adjacent=frozenset({frozenset({NORTH, SOUTH})}),
    )


def test_the_longest_matching_prefix_wins():
    assert a_table().zone_of("12-345").zone == "Z12"


def test_a_shorter_prefix_still_matches_when_nothing_beats_it():
    assert a_table().zone_of("19-111").zone == "Z1"


def test_a_code_no_prefix_claims_is_unroutable():
    with pytest.raises(UnroutableShipment):
        a_table().zone_of("99-999")


def test_two_equally_specific_prefixes_are_refused():
    table = ZoneTable(
        prefixes=[ZonePrefix("12", "ZA", NORTH), ZonePrefix("12", "ZB", SOUTH)],
    )
    with pytest.raises(AmbiguousPrefixes):
        table.zone_of("12-345")


def test_the_same_region_is_domestic():
    assert a_table().band_between("10-001", "19-999") == DOMESTIC


def test_adjacent_regions_are_regional():
    assert a_table().band_between("10-001", "20-001") == REGIONAL


def test_distant_regions_are_long_haul():
    assert a_table().band_between("10-001", "30-001") == LONG_HAUL
