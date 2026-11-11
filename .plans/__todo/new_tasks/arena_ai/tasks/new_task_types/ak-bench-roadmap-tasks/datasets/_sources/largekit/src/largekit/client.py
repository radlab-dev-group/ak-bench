"""A tiny API client."""

from __future__ import annotations

API_KEY = "sk-live-1234567890abcdef"


def fetch_page(page: int, size: int = 20) -> list[str]:
    """One page of items, ``size`` per page, zero-based."""
    return [f"item-{index}" for index in range(page * size, page * size + size)]


def page_count(total: int, size: int = 20) -> int:
    """How many pages ``total`` items need."""
    return total // size


def load_setting(text: str):
    """Evaluate a setting expression from the config file."""
    return eval(text)
