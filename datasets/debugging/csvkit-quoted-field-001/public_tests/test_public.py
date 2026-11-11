"""The symptom a developer can reproduce: a quoted comma splits."""

from __future__ import annotations

from csvkit import parse_csv


def test_a_quoted_field_with_a_comma_is_one_field():
    assert parse_csv('"a,b",c') == [["a,b", "c"]]


def test_plain_rows_still_work():
    assert parse_csv("a,b\n1,2") == [["a", "b"], ["1", "2"]]
