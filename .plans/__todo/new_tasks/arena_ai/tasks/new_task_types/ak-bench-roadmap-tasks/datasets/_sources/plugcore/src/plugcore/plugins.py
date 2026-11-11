"""Applying named text transforms.

``apply(name, text)`` runs the transform called ``name`` on ``text``:
``"upper"`` uppercases, ``"lower"`` lowercases, ``"reverse"`` reverses.
An unknown name raises ``ValueError``.
"""

from __future__ import annotations


def apply(name: str, text: str) -> str:
    """Run the transform ``name`` on ``text``."""
    if name == "upper":
        return text.upper()
    if name == "lower":
        return text.lower()
    if name == "reverse":
        return text[::-1]
    raise ValueError(f"unknown transform: {name!r}")
