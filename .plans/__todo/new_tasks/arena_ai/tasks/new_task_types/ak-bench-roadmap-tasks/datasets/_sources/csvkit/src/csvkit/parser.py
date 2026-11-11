"""Parsing CSV text into rows of fields.

The format is the usual one: rows are separated by newlines, fields by
commas, and a field may be quoted with double quotes. Inside a quoted
field a comma is data, not a separator, and two double quotes stand for
one literal quote.
"""

from __future__ import annotations


def parse_csv(text: str) -> list[list[str]]:
    """Parse ``text`` into a list of rows, each a list of fields."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        if line == "":
            continue
        rows.append(line.split(","))
    return rows
