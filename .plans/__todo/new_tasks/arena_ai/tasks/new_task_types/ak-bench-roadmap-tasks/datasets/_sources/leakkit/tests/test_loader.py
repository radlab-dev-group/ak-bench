"""The finished part of the fixture: parsing a number works.

The loader has no tests yet; that is part of what the review should
notice.
"""

from __future__ import annotations

from leakkit import parse_count


def test_parse_count_reads_a_number():
    assert parse_count("42") == 42


def test_parse_count_tolerates_garbage():
    assert parse_count("nope") == 0
