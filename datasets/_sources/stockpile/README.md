# stockpile

An inventory engine: stock arrives as **lots** with a receipt date and an
expiry, can be **reserved**, **committed** into an order, **cancelled** back,
**transferred** between warehouses, and **expired** out of availability.
Quantities are exact integers; the difficulty is in the rules, not the
arithmetic.

The FEFO allocation module is declared and specified to the unit, but its body
raises `NotImplementedError`; that is the shape of the feature task built on
this fixture. The rest of the suite is narrow on purpose, so a defect can hide
behind it. Run the suite with `pytest`.
