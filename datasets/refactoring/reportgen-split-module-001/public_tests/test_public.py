"""The target structure, in miniature: modules exist and output holds."""

from __future__ import annotations

from reportgen import generate
from reportgen.aggregate import summarize
from reportgen.format import render
from reportgen.io import write_report


def test_the_pieces_do_their_jobs(tmp_path):
    totals = summarize([("east", 100), ("west", 200), ("east", 50)])
    assert totals == {"east": 150, "west": 200}
    text = render(totals)
    assert text == "east: 150\nwest: 200\nTOTAL: 350\n"
    path = tmp_path / "r.txt"
    write_report(path, text)
    assert path.read_text(encoding="utf-8") == text


def test_generate_still_works(tmp_path):
    path = tmp_path / "r.txt"
    assert generate([("east", 100)], path) == "east: 100\nTOTAL: 100\n"
