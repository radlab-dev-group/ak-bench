"""Moving a month by a number of months.

Months are numbered 1 to 12. Adding months crosses year boundaries:
December plus one month is January of the next year, and January minus
one month is December of the previous year.
"""

from __future__ import annotations


def add_months(year: int, month: int, n: int) -> tuple[int, int]:
    """Return ``(year, month)`` moved by ``n`` months (``n`` may be negative)."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be between 1 and 12, got {month}")
    total = month - 1 + n
    new_month = total % 12 + 1
    new_year = year
    return new_year, new_month
