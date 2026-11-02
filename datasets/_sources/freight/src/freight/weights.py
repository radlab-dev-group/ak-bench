"""Billable weight: what a carrier charges for, not what a scale shows.

A carrier charges for the greater of two weights. The **actual** weight is what
the parcel weighs. The **volumetric** weight is what the space it occupies
weighs at the carrier's density, ``length * width * height / divisor``, where
the divisor is a property of the carrier and therefore of the quote, not of the
parcel.

The three steps, in order
    1. The volumetric weight is ``length_cm * width_cm * height_cm / divisor``,
       exact — it is not rounded here, because rounding before the comparison
       can change which of the two weights wins.
    2. The **preliminary** weight is the greater of the actual and the
       volumetric, and it is then raised to the carrier's **minimum billable
       weight**. A parcel lighter than the minimum is charged the minimum.
    3. The preliminary weight is rounded **up** to the carrier's billing step.
       With a step of half a kilogram, 3.01 kg bills as 3.5 kg and 3.0 kg bills
       as exactly 3.0 kg — a weight that already sits on the step does not
       climb.

    Step 3 is last and there is exactly one rounding. Rounding the volumetric
    weight first, or rounding before the minimum is applied, is the classic way
    to lose or gain a step, and a step is money.

All weights are ``Decimal`` end to end. A float divisor would make 3.0 kg look
like 3.0000000000000004 kg, and the last step would round it up to the next
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

ZERO = Decimal(0)


def volumetric_weight(
    length_cm: Decimal,
    width_cm: Decimal,
    height_cm: Decimal,
    divisor: Decimal,
) -> Decimal:
    """The density weight of a box: its volume divided by the carrier's divisor."""
    if divisor <= ZERO:
        raise ValueError(f"divisor must be positive, got {divisor}")
    return length_cm * width_cm * height_cm / divisor


def round_up_to_step(weight: Decimal, step: Decimal) -> Decimal:
    """Raise ``weight`` to the next multiple of ``step``; a weight on a step stays."""
    if step <= ZERO:
        raise ValueError(f"step must be positive, got {step}")
    if weight <= ZERO:
        return ZERO
    units = weight / step
    if units == units.to_integral_value(rounding=ROUND_FLOOR):
        return weight
    return (units.to_integral_value(rounding=ROUND_CEILING)) * step


@dataclass(frozen=True)
class BillableWeight:
    """The answer to "what does the carrier charge for", with its working shown."""

    actual: Decimal
    volumetric: Decimal
    basis: str
    charged: Decimal

    def is_volumetric_limited(self) -> bool:
        return self.basis == "volumetric"


def billable_weight(
    actual_kg: Decimal,
    length_cm: Decimal,
    width_cm: Decimal,
    height_cm: Decimal,
    *,
    divisor: Decimal,
    minimum_kg: Decimal,
    step_kg: Decimal,
) -> BillableWeight:
    """The carrier's billable weight for a parcel, in the three documented steps."""
    if actual_kg <= ZERO:
        raise ValueError(f"actual weight must be positive, got {actual_kg}")
    volumetric = volumetric_weight(length_cm, width_cm, height_cm, divisor)
    preliminary = max(actual_kg, volumetric)
    basis = "volumetric" if volumetric > actual_kg else "actual"
    if preliminary < minimum_kg:
        preliminary = minimum_kg
        basis = "minimum"
    return BillableWeight(
        actual=actual_kg,
        volumetric=volumetric,
        basis=basis,
        charged=round_up_to_step(preliminary, step_kg),
    )
