"""Generating a sales report.

``generate(rows, path)`` takes ``(region, amount_cents)`` rows,
summarizes the total per region, renders a text report, writes it to
``path``, and returns the text. The report lists regions in
alphabetical order, one per line as ``region: total``, followed by a
``TOTAL: <sum>`` line.
"""

from __future__ import annotations

from pathlib import Path


def generate(rows: list[tuple[str, int]], path: Path) -> str:
    """Summarize, render and write the report; return the text."""
    totals: dict[str, int] = {}
    for region, amount in rows:
        totals[region] = totals.get(region, 0) + amount
    lines = []
    for region in sorted(totals):
        lines.append(f"{region}: {totals[region]}")
    lines.append(f"TOTAL: {sum(totals.values())}")
    text = "\n".join(lines) + "\n"
    Path(path).write_text(text, encoding="utf-8")
    return text
