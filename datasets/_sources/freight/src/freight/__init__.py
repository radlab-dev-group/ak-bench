"""freight: zones, billable weight, rate cards and surcharges for one network.

The package is a benchmark fixture and is deliberately complete — a zone table
that reads postal codes, a billable-weight rule that rounds exactly once, a
rate card that refuses what it will not carry, and a rate-shopping module
whose body is the task — because the tasks built on it are about one rule
behaving wrongly, not about a missing system.
"""

from freight.errors import (
    AmbiguousPrefixes,
    FreightError,
    NoQuotableCarrier,
    UnknownCarrier,
    UnknownZone,
    UnroutableShipment,
)
from freight.pricing import (
    RateCard,
    RateTable,
    Shipment,
    Surcharge,
    SurchargeBook,
    round_cents,
)
from freight.shop import OVERSIZE_LIMIT_CM, Quote, Rejection, ShoppingResult, shop
from freight.weights import BillableWeight, billable_weight, volumetric_weight
from freight.zones import DOMESTIC, LONG_HAUL, REGIONAL, ZonePrefix, ZoneTable

__all__ = [
    "DOMESTIC",
    "LONG_HAUL",
    "OVERSIZE_LIMIT_CM",
    "REGIONAL",
    "AmbiguousPrefixes",
    "BillableWeight",
    "FreightError",
    "NoQuotableCarrier",
    "Quote",
    "RateCard",
    "RateTable",
    "Rejection",
    "Shipment",
    "ShoppingResult",
    "Surcharge",
    "SurchargeBook",
    "UnknownCarrier",
    "UnknownZone",
    "UnroutableShipment",
    "ZonePrefix",
    "ZoneTable",
    "billable_weight",
    "round_cents",
    "shop",
    "volumetric_weight",
]
