"""The refactoring, proven: target structure plus preserved behaviour.

These tests fail on the base commit (the target modules do not exist)
and pass once the generator is split.
"""

from __future__ import annotations

from reportgen import generate
from reportgen.aggregate import summarize
from reportgen.format import render
from reportgen.io import write_report


def test_summarize_totals_per_region():
    assert summarize([("east", 100), ("west", 200), ("east", 50)]) == {
        "east": 150,
        "west": 200,
    }
    assert summarize([]) == {}


def test_render_orders_regions_and_adds_the_total():
    assert render({"west": 200, "east": 150}) == "east: 150\nwest: 200\nTOTAL: 350\n"
    assert render({}) == "TOTAL: 0\n"


def test_write_report_writes_the_text(tmp_path):
    path = tmp_path / "r.txt"
    write_report(path, "hello\n")
    assert path.read_text(encoding="utf-8") == "hello\n"


def test_generate_behaviour_is_unchanged(tmp_path):
    path = tmp_path / "r.txt"
    text = generate([("east", 100), ("west", 200), ("east", 50)], path)
    assert text == "east: 150\nwest: 200\nTOTAL: 350\n"
    assert path.read_text(encoding="utf-8") == text
    assert generate([], path) == "TOTAL: 0\n"
