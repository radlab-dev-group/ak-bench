"""The vulnerability, proven from every side.

These tests fail on the base commit (the vulnerability is in the base
code) and pass once internal hosts are refused.
"""

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


def test_a_redirect_to_a_metadata_address_is_refused():
    pages = {
        "https://public.example/": (302, {"Location": "http://169.254.169.254/latest"}, ""),
        "http://169.254.169.254/latest": (200, {}, "credentials"),
    }
    with pytest.raises(ValueError):
        fetch("https://public.example/", transport_for(pages))


def test_a_direct_fetch_of_a_private_ip_is_refused():
    pages = {"http://192.168.1.10/": (200, {}, "secret")}
    with pytest.raises(ValueError):
        fetch("http://192.168.1.10/", transport_for(pages))


def test_a_direct_fetch_of_localhost_is_refused():
    pages = {"http://localhost:8080/": (200, {}, "secret")}
    with pytest.raises(ValueError):
        fetch("http://localhost:8080/", transport_for(pages))


def test_a_redirect_chain_ending_internal_is_refused():
    pages = {
        "https://public.example/a": (302, {"Location": "https://public.example/b"}, ""),
        "https://public.example/b": (302, {"Location": "http://10.0.0.5/"}, ""),
        "http://10.0.0.5/": (200, {}, "secret"),
    }
    with pytest.raises(ValueError):
        fetch("https://public.example/a", transport_for(pages))


def test_public_fetches_and_redirects_still_work():
    pages = {
        "https://public.example/old": (302, {"Location": "https://public.example/new"}, ""),
        "https://public.example/new": (200, {}, "new body"),
    }
    assert fetch("https://public.example/old", transport_for(pages)) == "new body"


def test_the_redirect_limit_still_applies():
    pages = {}
    for i in range(10):
        pages[f"https://public.example/{i}"] = (
            302, {"Location": f"https://public.example/{i + 1}"}, ""
        )
    pages["https://public.example/10"] = (200, {}, "end")
    with pytest.raises(ValueError):
        fetch("https://public.example/0", transport_for(pages))
