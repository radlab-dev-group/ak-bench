# freight

A freight rate-shopping engine: shipments move between postal codes through a
zone table, carriers quote from a published rate table, and the quote is
adjusted by surcharges that each have their own rule about what it applies to
and when it stacks. Money is exact integer cents and the rounding is
documented to the cent, because the benchmark tasks are about which rule
applies where, not about guessing a pricing policy.

The rate-shopping module is declared and specified to the cent, but its body
raises `NotImplementedError`; that is the shape of the benchmark task built on
this fixture. The rest of the suite is narrow on purpose, so a defect can hide
behind it. Run the suite with `pytest`.
