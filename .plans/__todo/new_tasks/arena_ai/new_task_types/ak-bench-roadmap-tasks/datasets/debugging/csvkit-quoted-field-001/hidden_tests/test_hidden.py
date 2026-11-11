"""The failing scenario, proven from every side.

These tests fail on the base commit (the defect is in the base code) and
pass once the parser is repaired.
"""

from __future__ import annotations

from csvkit import parse_csv


def test_a_quoted_field_with_a_comma_is_one_field():
    assert parse_csv('"a,b",c') == [["a,b", "c"]]


def test_several_quoted_fields_in_one_row():
    assert parse_csv('"a,b","c,d",e') == [["a,b", "c,d", "e"]]


def test_an_escaped_quote_inside_a_quoted_field():
    assert parse_csv('"say ""hi""",x') == [["say \"hi\"", "x"]]


def test_a_quoted_field_at_the_end_of_a_row():
    assert parse_csv('a,"b,c"') == [["a", "b,c"]]


def test_quoted_fields_across_rows():
    assert parse_csv('"a,b",c\n1,"2,3"') == [["a,b", "c"], ["1", "2,3"]]


def test_an_empty_quoted_field():
    assert parse_csv('"",a') == [["", "a"]]


def test_plain_rows_and_blank_lines_still_work():
    assert parse_csv("a,b\n\n1,2") == [["a", "b"], ["1", "2"]]
    assert parse_csv("") == []
