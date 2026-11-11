"""The finished part of the fixture: report behaviour.

These tests pin the behaviour the refactoring must preserve.
"""

from __future__ import annotations

from reportgen import generate


def test_generates_a_report(tmp_path):
    path = tmp_path / "report.txt"
    text = generate([("east", 100), ("west", 200), ("east", 50)], path)
    assert text == "east: 150\nwest: 200\nTOTAL: 350\n"
    assert path.read_text(encoding="utf-8") == text


def test_an_empty_report_has_only_a_total(tmp_path):
    path = tmp_path / "report.txt"
    assert generate([], path) == "TOTAL: 0\n"
