"""Zones: what a postal code means to a rate table, and what two of them mean.

A rate table does not know postal codes, it knows zones. Two lookups happen
here, and the order between them is the whole module.

Prefix lookup
    A postal code is matched against the prefixes of a zone table, and the
    **longest** prefix that matches wins. ``"12-345"`` against prefixes ``"1"``
    and ``"12-3"`` is the second one: a more specific prefix is a more specific
    statement about where the code is. Two prefixes of the same length that both
    match one code is a broken table, and it is refused when the table is built
    rather than guessed at during a lookup.

Region and band
    A zone belongs to a region. Two postal codes give a **band**, which is what
    a rate card is written against:

    * the same region is ``domestic``;
    * two regions that are adjacent in the region graph are ``regional``;
    * anything else is ``long_haul``.

    A code with no prefix match, or a zone with no region, makes the shipment
    unroutable rather than quietly long-haul: an invented band is a wrong price,
    and a missing lane is a lane the carrier should not be asked to quote.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from freight.errors import AmbiguousPrefixes, UnknownZone, UnroutableShipment

#: The three bands a rate card can be written against, cheapest first.
DOMESTIC = "domestic"
REGIONAL = "regional"
LONG_HAUL = "long_haul"


@dataclass(frozen=True)
class ZonePrefix:
    """One statement about where a postal code lives."""

    prefix: str
    zone: str
    region: str

    def __post_init__(self) -> None:
        if not self.prefix:
            raise ValueError("a zone prefix cannot be empty")


@dataclass
class ZoneTable:
    """Postal code prefixes, the zones they name, and the regions those zones are in."""

    prefixes: list[ZonePrefix] = field(default_factory=list)
    adjacent: frozenset[frozenset[str]] = frozenset()

    def __post_init__(self) -> None:
        self._by_prefix = {entry.prefix: entry for entry in self.prefixes}

    def zone_of(self, postal_code: str) -> ZonePrefix:
        """The entry whose prefix matches ``postal_code``, longest match winning."""
        matches = [entry for entry in self.prefixes if postal_code.startswith(entry.prefix)]
        if not matches:
            raise UnroutableShipment(postal_code, "-", "no prefix matches the postal code")
        longest = max(len(entry.prefix) for entry in matches)
        winners = sorted(entry.zone for entry in matches if len(entry.prefix) == longest)
        if len(set(winners)) > 1:
            raise AmbiguousPrefixes(
                f"{postal_code}: prefixes of length {longest} claim {', '.join(winners)}"
            )
        return self._by_prefix[max(matches, key=lambda entry: len(entry.prefix)).prefix]

    def region_of(self, postal_code: str) -> str:
        return self.zone_of(postal_code).region

    def are_adjacent(self, first: str, second: str) -> bool:
        return frozenset({first, second}) in self.adjacent

    def band_between(self, origin: str, destination: str) -> str:
        """The band a lane falls in: same region, adjacent regions, or neither."""
        origin_region = self.region_of(origin)
        destination_region = self.region_of(destination)
        if origin_region == destination_region:
            return DOMESTIC
        if self.are_adjacent(origin_region, destination_region):
            return REGIONAL
        return LONG_HAUL

    def zones(self) -> list[str]:
        return sorted({entry.zone for entry in self.prefixes})

    def require_zone(self, zone: str) -> ZonePrefix:
        for entry in self.prefixes:
            if entry.zone == zone:
                return entry
        raise UnknownZone(zone)
