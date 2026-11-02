"""The whole exception hierarchy of the freight engine.

Every failure the engine can produce is a :class:`FreightError`, so a caller
can catch one name. The subclasses name what was refused, because "this
cannot be quoted" is only useful when it says which rule refused it.
"""

from __future__ import annotations


class FreightError(Exception):
    """Base class for everything freight refuses."""


class UnknownCarrier(FreightError):
    """A carrier the table does not hold."""

    def __init__(self, carrier: str) -> None:
        super().__init__(f"unknown carrier: {carrier}")
        self.carrier = carrier


class UnknownZone(FreightError):
    """A zone the rate table does not rate."""

    def __init__(self, zone: str) -> None:
        super().__init__(f"no rate for zone: {zone}")
        self.zone = zone


class UnroutableShipment(FreightError):
    """The shipment cannot be routed through the zone table at all."""

    def __init__(self, origin: str, destination: str, reason: str) -> None:
        super().__init__(f"cannot route {origin} to {destination}: {reason}")
        self.origin = origin
        self.destination = destination
        self.reason = reason


class AmbiguousPrefixes(FreightError):
    """Two equally specific zone prefixes claim the same postal code."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"ambiguous zone prefixes: {detail}")
        self.detail = detail


class NoQuotableCarrier(FreightError):
    """No carrier quoted a price for the shipment."""

    def __init__(self, origin: str, destination: str) -> None:
        super().__init__(f"no carrier quoted for {origin} to {destination}")
        self.origin = origin
        self.destination = destination


class NegativeQuantity(FreightError):
    """A dimension the engine cannot price: zero or below."""

    def __init__(self, name: str, value: float) -> None:
        super().__init__(f"{name} must be positive, got {value}")
        self.name = name
        self.value = value
