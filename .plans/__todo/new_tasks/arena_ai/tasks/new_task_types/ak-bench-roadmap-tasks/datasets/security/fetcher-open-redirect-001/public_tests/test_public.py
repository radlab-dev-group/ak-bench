"""The symptom a developer can reproduce: a redirect to localhost is followed."""

from __future__ import annotations

import pytest

from fetcher import fetch


def transport_for(pages):
    def transport(url):
        return pages[url]
    return transport


def test_a_redirect_to_localhost_is_refused():
    pages = {
        "https://public.example/": (302, {"Location": "http://localhost/admin"}, ""),
        "http://localhost/admin": (200, {}, "secret"),
    }
    with pytest.raises(ValueError):
        fetch("https://public.example/", transport_for(pages))


def test_a_public_fetch_still_works():
    pages = {"https://public.example/": (200, {}, "hello")}
    assert fetch("https://public.example/", transport_for(pages)) == "hello"
