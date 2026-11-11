"""The finished part of the fixture: public hosts.

The suite deliberately never redirects to an internal host, so a
redirect-to-internal defect is invisible here.
"""

from __future__ import annotations

from fetcher import fetch


def transport_for(pages):
    def transport(url):
        return pages[url]
    return transport


def test_fetches_a_public_page():
    pages = {"https://public.example/": (200, {}, "hello")}
    assert fetch("https://public.example/", transport_for(pages)) == "hello"


def test_follows_a_public_redirect():
    pages = {
        "https://public.example/old": (302, {"Location": "https://public.example/new"}, ""),
        "https://public.example/new": (200, {}, "new body"),
    }
    assert fetch("https://public.example/old", transport_for(pages)) == "new body"
