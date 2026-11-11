"""The finished part of the fixture: plain, unquoted rows.

The suite deliberately never quotes a field, so a defect in how quoted
fields are read is invisible here.
"""

from __future__ import annotations

from csvkit import parse_csv


def test_plain_rows_split_on_commas():
    assert parse_csv("a,b,c\n1,2,3") == [["a", "b", "c"], ["1", "2", "3"]]


def test_a_single_field_row():
    assert parse_csv("hello") == [["hello"]]


def test_empty_text_has_no_rows():
    assert parse_csv("") == []


def test_blank_lines_are_skipped():
    assert parse_csv("a,b\n\n1,2") == [["a", "b"], ["1", "2"]]
