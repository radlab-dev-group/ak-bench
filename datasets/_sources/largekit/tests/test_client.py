"""The finished part of the fixture: fetching a page works.

Pagination math, settings and the key have no tests yet; that is part
of what the review should notice.
"""

from __future__ import annotations

from largekit import fetch_page


def test_fetch_page_returns_a_page():
    assert fetch_page(0, 3) == ["item-0", "item-1", "item-2"]
    assert fetch_page(1, 3) == ["item-3", "item-4", "item-5"]
